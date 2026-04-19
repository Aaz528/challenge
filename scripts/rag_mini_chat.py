#!/usr/bin/env python3
"""
Мини-чат с RAG и «памятью задачи»: история диалога, retrieval на каждый ход, ответ с источниками.

CLI: python scripts/rag_mini_chat.py
Программный API: run_mini_chat_turn(...)
"""
from __future__ import annotations

import argparse
import json
try:
    import readline  # noqa: F401 — улучшает input() в CLI
except ImportError:
    pass
import sys
from pathlib import Path
from typing import Any

from rag_qa import (
    _call_llm,
    _ensure_quotes,
    _merge_llm_answer,
    _parse_json_object,
    prepare_rag_context,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_task_memory() -> dict[str, Any]:
    return {
        "goal": "",
        "clarified": [],
        "constraints": [],
        "terms": {},
    }


def _normalize_task_memory(raw: Any, previous: dict[str, Any]) -> dict[str, Any]:
    base = dict(previous)
    if not isinstance(raw, dict):
        return base
    g = raw.get("goal")
    if isinstance(g, str) and g.strip():
        base["goal"] = g.strip()
    for key in ("clarified", "constraints"):
        val = raw.get(key)
        if isinstance(val, list):
            merged = list(base.get(key) or [])
            for x in val:
                s = str(x).strip()
                if s and s not in merged:
                    merged.append(s)
            base[key] = merged[:30]
    terms = raw.get("terms")
    if isinstance(terms, dict):
        out_terms = dict(base.get("terms") or {})
        for k, v in terms.items():
            ks = str(k).strip()
            vs = str(v).strip()
            if ks and vs:
                out_terms[ks] = vs
        base["terms"] = out_terms
    return base


def _format_history_block(messages: list[dict[str, str]], *, max_turns: int = 14) -> str:
    tail = messages[-max_turns:] if len(messages) > max_turns else messages
    lines: list[str] = []
    for m in tail:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        label = "Пользователь" if role == "user" else "Ассистент"
        lines.append(f"{label}: {content}")
    return "\n".join(lines).strip() or "(пусто)"


def _compose_retrieval_query(
    user_message: str,
    task_memory: dict[str, Any],
    *,
    max_chars: int = 6000,
) -> str:
    parts: list[str] = []
    g = (task_memory.get("goal") or "").strip()
    if g:
        parts.append(f"Цель диалога: {g}")
    for x in task_memory.get("clarified") or []:
        xs = str(x).strip()
        if xs:
            parts.append(f"Уточнение пользователя: {xs}")
    for x in task_memory.get("constraints") or []:
        xs = str(x).strip()
        if xs:
            parts.append(f"Ограничение: {xs}")
    terms = task_memory.get("terms") or {}
    if isinstance(terms, dict) and terms:
        for k, v in list(terms.items())[:24]:
            parts.append(f"Термин «{k}»: {v}")
    parts.append(f"Текущий вопрос:\n{user_message.strip()}")
    text = "\n".join(parts).strip()
    return text[:max_chars]


def _chat_system_prompt() -> str:
    return (
        "Ты инженерный ассистент по кодовой базе из приложенного контекста индекса. "
        "Отвечай по-русски. Любые факты о коде — только из блока «Контекст из индекса»; "
        "если контекста недостаточно, скажи об этом и предложи уточнить вопрос. "
        "Веди «память задачи»: цель диалога, что пользователь уже уточнил, ограничения и зафиксированные термины. "
        "Обновляй память на основе истории и нового сообщения (не теряй уже зафиксированное без причины). "
        "Верни ТОЛЬКО один JSON-объект без markdown по схеме:\n"
        '{"answer":"текст ответа","task_memory":{"goal":"строка","clarified":["..."],"constraints":["..."],"terms":{"ключ":"значение"}},'
        '"quotes":[{"chunk_id":"...","text":"подстрока из контекста"}]}\n'
        "Поле quotes: если в контексте есть чанки — одна или несколько коротких дословных цитат с chunk_id из контекста; "
        "если контекста нет — пустой массив."
    )


def run_mini_chat_turn(
    user_message: str,
    *,
    history: list[dict[str, str]],
    task_memory: dict[str, Any] | None,
    db_path: Path,
    strategy: str = "structured",
    top_k_before: int = 20,
    top_k_after: int = 5,
    sim_threshold: float = 0.12,
    answer_min_score: float | None = None,
    max_context_chars: int = 5000,
    rewrite_mode: str = "heuristic",
    rerank_mode: str = "hybrid",
) -> dict[str, Any]:
    """Один ход мини-чата: RAG + JSON-ответ + обновлённая память задачи."""
    tm_prev = dict(task_memory) if task_memory else _default_task_memory()
    retrieval_query = _compose_retrieval_query(user_message, tm_prev)
    prep = prepare_rag_context(
        retrieval_query,
        db_path=db_path,
        strategy=strategy,
        top_k=top_k_after,
        max_context_chars=max_context_chars,
        rewrite_mode=rewrite_mode,
        rerank_mode=rerank_mode,
        top_k_before=top_k_before,
        top_k_after=top_k_after,
        sim_threshold=sim_threshold,
        answer_min_score=answer_min_score,
    )

    if prep.get("status") == "dont_know":
        context_block = (
            "(Релевантных фрагментов в индексе для запроса не найдено — ответь кратко, без выдуманных деталей кода, "
            "предложи переформулировать вопрос в терминах проекта.)"
        )
        chunks_after: list = []
        sources: list = []
        dont_know = True
        dont_know_reason = prep.get("dont_know_reason")
    else:
        context_block = str(prep["context"])
        chunks_after = prep["chunks_after"]  # type: ignore[assignment]
        sources = prep["sources"]
        dont_know = False
        dont_know_reason = None

    hist = _format_history_block(history)
    tm_json = json.dumps(tm_prev, ensure_ascii=False, indent=2)
    user_block = (
        f"--- История (последние реплики) ---\n{hist}\n\n"
        f"--- Память задачи (текущее состояние) ---\n{tm_json}\n\n"
        f"--- Контекст из индекса ---\n{context_block}\n\n"
        f"--- Новое сообщение пользователя ---\n{user_message.strip()}"
    )
    messages = [
        {"role": "system", "content": _chat_system_prompt()},
        {"role": "user", "content": user_block},
    ]
    out: dict[str, Any] = {
        "answer": "",
        "sources": sources,
        "quotes": [],
        "task_memory": tm_prev,
        "dont_know": dont_know,
        "dont_know_reason": dont_know_reason,
        "retrieval_query": retrieval_query,
        "query_rewritten": prep.get("query_rewritten"),
        "fallback": False,
    }
    if dont_know and isinstance(prep, dict):
        out["rag_meta"] = {k: v for k, v in prep.items() if k != "status"}

    try:
        raw = _call_llm(messages, json_object=True)
        parsed = _parse_json_object(raw) or {}
        answer = _merge_llm_answer(parsed)
        if not answer:
            answer = "Не удалось сформулировать ответ."
        tm_new = _normalize_task_memory(parsed.get("task_memory"), tm_prev)
        quotes = _ensure_quotes(parsed, chunks_after) if chunks_after else []
        out["answer"] = answer
        out["task_memory"] = tm_new
        out["quotes"] = quotes
    except Exception as e:
        out["fallback"] = True
        out["answer"] = (
            f"[Локальный / ошибка LLM: {e}]\n"
            "Кратко: проверьте OPENAI_API_KEY и сеть. Память задачи не обновлена автоматически."
        )
        out["task_memory"] = tm_prev
        out["quotes"] = []
    return out


def _load_session(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"messages": [], "task_memory": _default_task_memory()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"messages": [], "task_memory": _default_task_memory()}
    if not isinstance(data, dict):
        return {"messages": [], "task_memory": _default_task_memory()}
    msgs = data.get("messages")
    if not isinstance(msgs, list):
        msgs = []
    tm = data.get("task_memory")
    if not isinstance(tm, dict):
        tm = _default_task_memory()
    else:
        tm = _normalize_task_memory(tm, _default_task_memory())
    return {"messages": msgs, "task_memory": tm}


def _save_session(path: Path, session: dict[str, Any]) -> None:
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cli() -> None:
    root = _project_root()
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:
        pass

    p = argparse.ArgumentParser(description="Мини-чат RAG + память задачи (CLI).")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--session", default="rag_mini_chat_session.json", help="Файл сессии (история + память)")
    p.add_argument("--strategy", default="structured", choices=["fixed", "structured", "all"])
    p.add_argument("--top-k-before", type=int, default=20)
    p.add_argument("--top-k-after", type=int, default=5)
    p.add_argument("--sim-threshold", type=float, default=0.12)
    args = p.parse_args()
    db_path = (root / args.db_path).resolve()
    session_path = Path(args.session)
    if not session_path.is_absolute():
        session_path = (root / session_path).resolve()

    session = _load_session(session_path)
    print("Мини-чат RAG + память задачи. Команды: /quit /reset /memory /help")
    print(f"Сессия: {session_path} | DB: {db_path}")

    while True:
        try:
            line = input("\nВы> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break
        if not line:
            continue
        if line in ("/quit", "/q"):
            _save_session(session_path, session)
            print("Сессия сохранена. Пока.")
            break
        if line == "/help":
            print("/quit /reset /memory — выход, сброс, показать память задачи")
            continue
        if line == "/reset":
            session = {"messages": [], "task_memory": _default_task_memory()}
            _save_session(session_path, session)
            print("История и память сброшены.")
            continue
        if line == "/memory":
            print(json.dumps(session["task_memory"], ensure_ascii=False, indent=2))
            continue

        session["messages"].append({"role": "user", "content": line})
        turn = run_mini_chat_turn(
            line,
            history=session["messages"][:-1],
            task_memory=session["task_memory"],
            db_path=db_path,
            strategy=args.strategy,
            top_k_before=args.top_k_before,
            top_k_after=args.top_k_after,
            sim_threshold=args.sim_threshold,
        )
        session["task_memory"] = turn["task_memory"]
        session["messages"].append({"role": "assistant", "content": turn["answer"]})
        _save_session(session_path, session)

        print("\n--- Ассистент ---")
        print(turn["answer"])
        print("\n--- Источники (RAG) ---")
        if turn.get("dont_know"):
            print(f"(нет: {turn.get('dont_know_reason')})")
        for s in turn.get("sources") or []:
            print(
                f"- {s.get('file', '')} | {s.get('section', '')} | id={s.get('chunk_id', '')} "
                f"| score={float(s.get('score', 0)):.4f}"
            )
        if turn.get("quotes"):
            print("\n--- Цитаты ---")
            for q in turn["quotes"][:6]:
                t = str(q.get("text", "")).replace("\n", " ")[:200]
                print(f"  [{q.get('chunk_id', '')}] {t}…")


def run_scenarios(
    *,
    db_path: Path,
    scenarios_path: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Прогон сценариев из JSON; возвращает сводку проверок."""
    payload = json.loads(scenarios_path.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios") if isinstance(payload, dict) else None
    if not isinstance(scenarios, list):
        raise SystemExit("Invalid scenarios file")

    summary: dict[str, Any] = {"scenarios": [], "ok": True}
    report_lines: list[str] = [
        "# Мини-чат RAG: проверка сценариев",
        "",
        f"- DB: `{db_path}`",
        f"- Файл: `{scenarios_path}`",
        "",
    ]

    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("id", "?"))
        title = str(sc.get("title", ""))
        messages = sc.get("messages")
        if not isinstance(messages, list) or not messages:
            continue
        history: list[dict[str, str]] = []
        tm: dict[str, Any] = _default_task_memory()
        turns_ok = 0
        sources_ok = 0
        goal_or_clarified = False
        turn_logs: list[str] = []

        for i, raw_u in enumerate(messages):
            user_msg = str(raw_u).strip()
            if not user_msg:
                continue
            turn = run_mini_chat_turn(
                user_msg,
                history=history,
                task_memory=tm,
                db_path=db_path,
            )
            tm = turn["task_memory"]
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": turn["answer"]})
            turns_ok += 1
            srcs = turn.get("sources") or []
            if not turn.get("dont_know") and len(srcs) > 0:
                sources_ok += 1
            if (tm.get("goal") or "").strip() or len(tm.get("clarified") or []) >= 2:
                goal_or_clarified = True
            turn_logs.append(
                f"  - turn {i + 1}: dont_know={turn.get('dont_know')} sources={len(srcs)} "
                f"goal_set={bool((tm.get('goal') or '').strip())}"
            )

        min_sources_turns = max(6, int(0.5 * turns_ok)) if turns_ok else 0
        sc_ok = turns_ok >= 10 and goal_or_clarified and sources_ok >= min_sources_turns
        summary["scenarios"].append(
            {
                "id": sid,
                "title": title,
                "turns": turns_ok,
                "sources_with_hits": sources_ok,
                "goal_or_clarified_ok": goal_or_clarified,
                "scenario_ok": sc_ok,
            }
        )
        if not sc_ok:
            summary["ok"] = False

        report_lines.append(f"## {sid}: {title}")
        report_lines.append("")
        report_lines.extend(turn_logs)
        report_lines.append("")
        report_lines.append(
            f"- Цель/уточнения в памяти: **{goal_or_clarified}**; ходов с источниками: **{sources_ok}/{turns_ok}**"
        )
        report_lines.append("")

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return summary


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--scenarios":
        root = _project_root()
        try:
            from dotenv import load_dotenv

            load_dotenv(root / ".env")
        except ImportError:
            pass
        sp = root / "docs" / "rag_mini_chat_scenarios.json"
        rp = root / "docs" / "rag_mini_chat_scenarios_report.md"
        db = root / "rag_index.db"
        out = run_scenarios(db_path=db, scenarios_path=sp, report_path=rp)
        print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
        print(f"Report: {rp}", flush=True)
        raise SystemExit(0 if out.get("ok") else 1)

    run_cli()


if __name__ == "__main__":
    main()
