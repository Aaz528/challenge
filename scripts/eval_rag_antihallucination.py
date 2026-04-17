#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from rag_qa import answer_with_rag


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Проверка 10 контрольных вопросов: источники, цитаты, согласованность ответа с цитатами."
    )
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--questions-path", default="docs/rag_control_questions.json")
    p.add_argument("--report-path", default="docs/rag_antihallucination_report.md")
    p.add_argument("--strategy", choices=["fixed", "structured", "all"], default="structured")
    p.add_argument("--top-k-before", type=int, default=20)
    p.add_argument("--top-k-after", type=int, default=5)
    p.add_argument("--sim-threshold", type=float, default=0.12)
    p.add_argument("--answer-min-score", type=float, default=None)
    return p.parse_args()


def _wordish_tokens(text: str, *, min_len: int = 4) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9_]{%d,}" % min_len, text)}


def _answer_aligned_with_quotes(answer: str, quotes_text: str) -> bool:
    """Эвристика: доля значимых слов ответа, встречающихся в объединённых цитатах."""
    if not answer.strip() or not quotes_text.strip():
        return False
    aw = _wordish_tokens(answer)
    qw = _wordish_tokens(quotes_text)
    if not aw:
        return True
    hit = len(aw & qw)
    return hit >= max(2, int(0.2 * len(aw)))


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    db_path = (root / args.db_path).resolve()
    questions_path = (root / args.questions_path).resolve()
    report_path = (root / args.report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < 1:
        raise SystemExit("Control questions file is empty or invalid.")

    intro: list[str] = []
    intro.append("# RAG: источники, цитаты, анти-галлюцинации")
    intro.append("")
    intro.append(f"- Файл вопросов: `{questions_path}`")
    intro.append(f"- Индекс: `{db_path}`")
    intro.append(f"- strategy={args.strategy}, top_k_before={args.top_k_before}, top_k_after={args.top_k_after}")
    intro.append(f"- sim_threshold={args.sim_threshold}, answer_min_score={args.answer_min_score}")
    intro.append("- Режим: rewrite=heuristic, rerank=hybrid (как «улучшенный» профиль)")
    intro.append("")
    intro.append(
        "Проверки: для каждого ответа with_rag — непустые `sources` и `quotes`, "
        "если не сработал режим `dont_know`; плюс эвристика согласованности ответа с цитатами."
    )
    intro.append("")

    lines: list[str] = []
    ok_sources = 0
    ok_quotes = 0
    ok_align = 0
    dont_know_n = 0
    n = 0

    for i, row in enumerate(payload, start=1):
        qid = str(row.get("id", f"q{i:02d}"))
        question = str(row.get("question", "")).strip()
        expectation = str(row.get("expectation", "")).strip()
        if not question:
            continue
        n += 1
        rag = answer_with_rag(
            question,
            db_path=db_path,
            strategy=args.strategy,
            top_k=args.top_k_after,
            top_k_before=args.top_k_before,
            top_k_after=args.top_k_after,
            rewrite_mode="heuristic",
            rerank_mode="hybrid",
            sim_threshold=float(args.sim_threshold),
            answer_min_score=args.answer_min_score,
            max_context_chars=6500,
        )
        dk = bool(rag.get("dont_know"))
        if dk:
            dont_know_n += 1
        sources = rag.get("sources") or []
        quotes = rag.get("quotes") or []
        ans = str(rag.get("answer", ""))
        joined_q = " ".join(str(q.get("text", "")) for q in quotes if isinstance(q, dict))

        has_src = dk or len(sources) > 0
        has_q = dk or len(quotes) > 0
        aligned = dk or _answer_aligned_with_quotes(ans, joined_q)

        ok_sources += 1 if has_src else 0
        ok_quotes += 1 if has_q else 0
        ok_align += 1 if aligned else 0

        lines.append(f"## {qid}")
        lines.append("")
        lines.append(f"**Вопрос:** {question}")
        lines.append("")
        lines.append(f"**Ожидание (ref):** {expectation}")
        lines.append("")
        lines.append(f"- `dont_know`: {dk}")
        if dk:
            lines.append(f"- причина: `{rag.get('dont_know_reason')}`")
            lines.append(
                f"- max_score={rag.get('relevance_max_score')}, порог={rag.get('relevance_threshold')}"
            )
        lines.append(f"- источников: {len(sources)}, цитат: {len(quotes)}")
        lines.append(f"- проверка sources: {'OK' if has_src else 'FAIL'}")
        lines.append(f"- проверка quotes: {'OK' if has_q else 'FAIL'}")
        lines.append(f"- согласованность ответа с цитатами (эвристика): {'OK' if aligned else 'FAIL'}")
        lines.append("")
        lines.append("**Ответ:**")
        lines.append("")
        lines.append(ans)
        lines.append("")
        if sources:
            lines.append("**Источники:**")
            for s in sources[:12]:
                lines.append(
                    f"- `{s.get('file','')}` / `{s.get('section','')}` / chunk_id=`{s.get('chunk_id','')}` "
                    f"(score={float(s.get('score',0)):.4f})"
                )
            lines.append("")
        if quotes:
            lines.append("**Цитаты:**")
            for q in quotes[:8]:
                qt = str(q.get("text", "")).replace("\n", " ")
                if len(qt) > 420:
                    qt = qt[:420] + "…"
                lines.append(f"- chunk_id=`{q.get('chunk_id','')}`: {qt}")
            lines.append("")
        lines.append("---")
        lines.append("")

    if n == 0:
        summary = ["## Сводка", "", "- в файле вопросов не найдено пригодных записей", ""]
    else:
        summary = [
            f"## Сводка ({n} вопросов)",
            "",
            f"- dont_know: {dont_know_n}/{n}",
            f"- источники (или dont_know): {ok_sources}/{n}",
            f"- цитаты (или dont_know): {ok_quotes}/{n}",
            f"- согласованность (или dont_know): {ok_align}/{n}",
            "",
        ]
    report_path.write_text("\n".join(intro + summary + lines), encoding="utf-8")
    print(f"Report written: {report_path}")
    if n:
        print(
            f"Scores: sources={ok_sources}/{n}, quotes={ok_quotes}/{n}, "
            f"align={ok_align}/{n}, dont_know={dont_know_n}/{n}"
        )


if __name__ == "__main__":
    main()
