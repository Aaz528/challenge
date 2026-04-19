#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from rag_index_lib import Embedder, cosine_similarity


@dataclass(frozen=True)
class RetrievedChunk:
    score: float
    strategy: str
    chunk_id: str
    section: str
    text: str
    meta: dict[str, Any]
    rerank_score: float = 0.0
    keyword_overlap: int = 0


def _call_llm(messages: list[dict[str, str]], *, json_object: bool = False) -> str:
    load_dotenv()
    if os.environ.get("RAG_QA_FORCE_LOCAL", "").strip().lower() in ("1", "true", "yes", "on"):
        raise RuntimeError("local mode requested")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", "deepseek-chat").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    timeout_sec = 45
    raw_to = os.environ.get("RAG_QA_TIMEOUT_SEC", "").strip()
    if raw_to:
        try:
            timeout_sec = max(10, int(raw_to))
        except ValueError:
            timeout_sec = 45
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1400,
    }
    if json_object:
        body["response_format"] = {"type": "json_object"}
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout_sec,
    )
    if json_object and resp.status_code >= 400:
        body.pop("response_format", None)
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout_sec,
        )
    resp.raise_for_status()
    data = resp.json()
    text = str(data["choices"][0]["message"]["content"]).strip()
    if not text:
        raise RuntimeError("LLM returned empty text")
    return text


def _strip_json_fence(raw: str) -> str:
    t = raw.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(_strip_json_fence(raw))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _quote_is_substring(quote: str, chunk_text: str) -> bool:
    q = _norm_ws(quote)
    if len(q) < 4:
        return False
    c = _norm_ws(chunk_text)
    return q in c


def _chunk_by_id(chunks: list[RetrievedChunk]) -> dict[str, RetrievedChunk]:
    return {c.chunk_id: c for c in chunks}


def _repair_or_drop_quote(
    chunk_id: str, quote: str, by_id: dict[str, RetrievedChunk], *, max_len: int = 320
) -> dict[str, str] | None:
    ch = by_id.get(chunk_id)
    if ch is None:
        return None
    qt = quote.strip()
    if qt and _quote_is_substring(qt, ch.text):
        return {"chunk_id": chunk_id, "text": qt[:max_len]}
    snippet = _norm_ws(ch.text.replace("\n", " "))[:max_len]
    if len(snippet) < 12:
        return None
    return {"chunk_id": chunk_id, "text": snippet}


def _ensure_quotes(
    parsed: dict[str, Any],
    chunks_after: list[RetrievedChunk],
) -> list[dict[str, str]]:
    by_id = _chunk_by_id(chunks_after)
    raw_list = parsed.get("quotes")
    if not isinstance(raw_list, list):
        raw_list = []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("chunk_id", "")).strip()
        text = str(item.get("text", item.get("quote", ""))).strip()
        if not cid:
            continue
        fixed = _repair_or_drop_quote(cid, text, by_id)
        if fixed is None:
            continue
        key = f"{fixed['chunk_id']}::{fixed['text'][:40]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(fixed)
    if not out and chunks_after:
        for ch in chunks_after[:5]:
            snippet = _norm_ws(ch.text.replace("\n", " "))[:300]
            out.append({"chunk_id": ch.chunk_id, "text": snippet})
    return out


def _merge_llm_answer(parsed: dict[str, Any]) -> str:
    ans = parsed.get("answer")
    if isinstance(ans, str) and ans.strip():
        return ans.strip()
    return ""


def _resolved_answer_min_score(sim_threshold: float, answer_min_score: float | None) -> float:
    if answer_min_score is not None:
        return float(answer_min_score)
    raw = os.environ.get("RAG_ANSWER_MIN_SCORE", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return float(sim_threshold)


def _structured_fallback_answer(question: str, chunks: list[RetrievedChunk]) -> tuple[str, list[dict[str, str]]]:
    if not chunks:
        return (
            "Локальный fallback: релевантные чанки не переданы. "
            f"Вопрос: {question}",
            [],
        )
    lines = [
        "Локальный fallback-ответ (LLM недоступен): кратко по найденным фрагментам.",
        "",
    ]
    quotes: list[dict[str, str]] = []
    for ch in chunks[:5]:
        snippet = _norm_ws(ch.text.replace("\n", " "))[:280]
        quotes.append({"chunk_id": ch.chunk_id, "text": snippet})
        lines.append(
            f"- [{ch.meta.get('file', '')}] {ch.section} (chunk_id={ch.chunk_id}, score={ch.score:.4f}): {snippet}"
        )
    return "\n".join(lines), quotes


def _dont_know_payload(
    *,
    question: str,
    chunks_before: list[RetrievedChunk],
    chunks_after: list[RetrievedChunk],
    removed: list[RetrievedChunk],
    max_score: float | None,
    threshold: float,
    reason: str,
    query_original: str,
    query_rewritten: str,
    rewrite_mode: str,
    rerank_mode: str,
    sim_threshold: float,
    k_before: int,
    k_after: int,
    filtered_out: list[dict[str, Any]],
    answer_override: str | None = None,
    keyword_overlap_max: int | None = None,
    keyword_overlap_required: int | None = None,
    answer_min_score: float | None = None,
) -> dict[str, Any]:
    _ = question
    if answer_override is not None:
        msg = answer_override
    else:
        msg = (
            "Не могу надёжно ответить по текущему индексу: релевантность лучших фрагментов ниже порога "
            f"({max_score if max_score is not None else 'n/a'} < {threshold:g}). "
            "Уточните вопрос, укажите файл или область проекта."
        )
    out: dict[str, Any] = {
        "mode": "with_rag",
        "answer": msg,
        "sources": [],
        "quotes": [],
        "dont_know": True,
        "dont_know_reason": reason,
        "relevance_max_score": max_score,
        "relevance_threshold": threshold,
        "retrieved_before_count": len(chunks_before),
        "retrieved_count": len(chunks_after),
        "query_original": query_original,
        "query_rewritten": query_rewritten,
        "rewrite_mode": rewrite_mode,
        "rerank_mode": rerank_mode,
        "sim_threshold": sim_threshold,
        "top_k_before": k_before,
        "top_k_after": k_after,
        "filtered_out": filtered_out,
    }
    if answer_min_score is not None:
        out["answer_min_score"] = answer_min_score
    if keyword_overlap_max is not None:
        out["keyword_overlap_max"] = keyword_overlap_max
    if keyword_overlap_required is not None:
        out["keyword_overlap_required"] = keyword_overlap_required
    return out


def _rewrite_query(question: str, mode: str) -> str:
    q = question.strip()
    if mode == "none":
        return q
    # heuristic rewrite to retrieval-friendly query
    cleaned = re.sub(r"\s+", " ", q.lower()).strip()
    for noise in ("пожалуйста", "подскажи", "расскажи", "объясни", "кратко"):
        cleaned = cleaned.replace(noise, "").strip()
    hints: list[str] = []
    if "mcp" in cleaned:
        hints.extend(["mcp", "tool", "server", "chat_service.py", "api/main.py"])
    if "sse" in cleaned or "stream" in cleaned or "поток" in cleaned:
        hints.extend(["sse", "stream", "send_message_stream", "api/main.py"])
    if "погод" in cleaned:
        hints.extend(["weather", "/api/weather/irkutsk", "api/main.py"])
    if "памят" in cleaned:
        hints.extend(["working memory", "refresh_working_memory_auto", "chat_service.py"])
    hint_tail = " ".join(dict.fromkeys(hints))
    if hint_tail:
        return f"{cleaned} {hint_tail}".strip()
    return cleaned


def _retrieve(
    db_path: Path,
    question: str,
    *,
    strategy: str,
    top_k: int,
) -> list[RetrievedChunk]:
    conn = sqlite3.connect(str(db_path))
    if strategy == "all":
        where = ""
        params: tuple[object, ...] = ()
    else:
        where = "WHERE c.strategy = ?"
        params = (strategy,)
    rows = conn.execute(
        f"""
        SELECT c.strategy, c.chunk_id, c.section, c.text, c.metadata_json, e.vector_json
        FROM chunks c
        JOIN embeddings e ON e.chunk_row_id = c.id
        {where}
        ORDER BY c.id
        """,
        params,
    ).fetchall()
    conn.close()
    if not rows:
        return []
    embedder = Embedder()
    qv = embedder.embed_query(question)
    scored: list[RetrievedChunk] = []
    for strategy_v, chunk_id, section, text, metadata_json, vector_json in rows:
        vec = [float(x) for x in json.loads(str(vector_json))]
        scored.append(
            RetrievedChunk(
                score=cosine_similarity(qv, vec),
                strategy=str(strategy_v),
                chunk_id=str(chunk_id),
                section=str(section),
                text=str(text),
                meta=json.loads(str(metadata_json)),
            )
        )
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[: max(1, top_k)]


def _keyword_overlap(query: str, text: str) -> int:
    q_words = {w for w in re.findall(r"[a-zA-Zа-яА-Я0-9_]{4,}", query.lower())}
    if not q_words:
        return 0
    t = text.lower()
    return sum(1 for w in q_words if w in t)


def _max_keyword_overlap_across_chunks(query: str, chunks: list[RetrievedChunk]) -> int:
    """Сколько значимых слов запроса (≥4 символа) попало хотя бы в один чанк (section+text).

    Возвращает -1, если в запросе нет ни одного такого слова — тогда порог по пересечению не применяем.
    """
    q_words = {w for w in re.findall(r"[a-zA-Zа-яА-Я0-9_]{4,}", query.lower())}
    if not q_words:
        return -1
    best = 0
    for ch in chunks:
        best = max(best, _keyword_overlap(query, f"{ch.section}\n{ch.text}"))
    return best


def _resolved_min_keyword_overlap() -> int:
    raw = os.environ.get("RAG_MIN_QUERY_TERM_OVERLAP", "1").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def _rerank_and_filter(
    query_for_retrieval: str,
    chunks_before: list[RetrievedChunk],
    *,
    rerank_mode: str,
    sim_threshold: float,
    top_k_after: int,
) -> tuple[list[RetrievedChunk], list[RetrievedChunk]]:
    if rerank_mode == "none":
        selected = chunks_before[: max(1, top_k_after)]
        return selected, []

    scored: list[RetrievedChunk] = []
    removed: list[RetrievedChunk] = []
    for ch in chunks_before:
        kw = _keyword_overlap(query_for_retrieval, f"{ch.section}\n{ch.text}")
        sec_bonus = 0.02 if ("def " in ch.section or "class " in ch.section) else 0.0
        hybrid = (0.75 * ch.score) + (0.05 * min(kw, 5)) + sec_bonus
        with_meta = RetrievedChunk(
            score=ch.score,
            strategy=ch.strategy,
            chunk_id=ch.chunk_id,
            section=ch.section,
            text=ch.text,
            meta=ch.meta,
            rerank_score=hybrid,
            keyword_overlap=kw,
        )
        if ch.score >= sim_threshold:
            scored.append(with_meta)
        else:
            removed.append(with_meta)

    if rerank_mode == "threshold":
        scored.sort(key=lambda x: x.score, reverse=True)
    else:  # hybrid
        scored.sort(key=lambda x: x.rerank_score, reverse=True)

    # diversify files a bit to reduce near-duplicates
    result: list[RetrievedChunk] = []
    per_file: dict[str, int] = {}
    max_per_file = 2
    for ch in scored:
        f = str(ch.meta.get("file", ""))
        if per_file.get(f, 0) >= max_per_file:
            continue
        per_file[f] = per_file.get(f, 0) + 1
        result.append(ch)
        if len(result) >= max(1, top_k_after):
            break

    # fallback if threshold was too strict
    if not result and chunks_before:
        best = chunks_before[: max(1, top_k_after)]
        return best, removed

    return result, removed


def prepare_rag_context(
    question: str,
    *,
    db_path: Path,
    strategy: str = "structured",
    top_k: int = 5,
    max_context_chars: int = 6000,
    rewrite_mode: str = "none",
    rerank_mode: str = "none",
    top_k_before: int | None = None,
    top_k_after: int | None = None,
    sim_threshold: float = 0.12,
    answer_min_score: float | None = None,
) -> dict[str, Any]:
    """Подготовка retrieval: либо dont_know (как в answer_with_rag), либо ok + chunks + context."""
    query_original = question.strip()
    query_rewritten = _rewrite_query(query_original, rewrite_mode)
    k_before = max(1, int(top_k_before if top_k_before is not None else max(top_k, 12)))
    k_after = max(1, int(top_k_after if top_k_after is not None else top_k))
    min_for_answer = _resolved_answer_min_score(sim_threshold, answer_min_score)

    chunks_before = _retrieve(db_path, query_rewritten, strategy=strategy, top_k=k_before)
    chunks_after, removed = _rerank_and_filter(
        query_rewritten,
        chunks_before,
        rerank_mode=rerank_mode,
        sim_threshold=sim_threshold,
        top_k_after=k_after,
    )
    filtered_out = [
        {
            "chunk_id": c.chunk_id,
            "score": c.score,
            "file": c.meta.get("file", ""),
            "section": c.section,
        }
        for c in removed[:20]
    ]

    if not chunks_before:
        payload = _dont_know_payload(
            question=query_original,
            chunks_before=chunks_before,
            chunks_after=chunks_after,
            removed=removed,
            max_score=None,
            threshold=min_for_answer,
            reason="no_chunks_in_index",
            query_original=query_original,
            query_rewritten=query_rewritten,
            rewrite_mode=rewrite_mode,
            rerank_mode=rerank_mode,
            sim_threshold=sim_threshold,
            k_before=k_before,
            k_after=k_after,
            filtered_out=filtered_out,
            answer_min_score=min_for_answer,
        )
        payload["status"] = "dont_know"
        return payload

    if not chunks_after:
        payload = _dont_know_payload(
            question=query_original,
            chunks_before=chunks_before,
            chunks_after=chunks_after,
            removed=removed,
            max_score=None,
            threshold=min_for_answer,
            reason="no_chunks_after_rerank",
            query_original=query_original,
            query_rewritten=query_rewritten,
            rewrite_mode=rewrite_mode,
            rerank_mode=rerank_mode,
            sim_threshold=sim_threshold,
            k_before=k_before,
            k_after=k_after,
            filtered_out=filtered_out,
            answer_min_score=min_for_answer,
        )
        payload["status"] = "dont_know"
        return payload

    max_score = max(c.score for c in chunks_after)
    if max_score < min_for_answer:
        payload = _dont_know_payload(
            question=query_original,
            chunks_before=chunks_before,
            chunks_after=chunks_after,
            removed=removed,
            max_score=max_score,
            threshold=min_for_answer,
            reason="below_relevance_threshold",
            query_original=query_original,
            query_rewritten=query_rewritten,
            rewrite_mode=rewrite_mode,
            rerank_mode=rerank_mode,
            sim_threshold=sim_threshold,
            k_before=k_before,
            k_after=k_after,
            filtered_out=filtered_out,
            answer_min_score=min_for_answer,
        )
        payload["status"] = "dont_know"
        return payload

    min_kw = _resolved_min_keyword_overlap()
    kw_max = _max_keyword_overlap_across_chunks(query_original, chunks_after)
    if min_kw > 0 and kw_max >= 0 and kw_max < min_kw:
        payload = _dont_know_payload(
            question=query_original,
            chunks_before=chunks_before,
            chunks_after=chunks_after,
            removed=removed,
            max_score=max_score,
            threshold=min_for_answer,
            reason="no_query_term_overlap",
            query_original=query_original,
            query_rewritten=query_rewritten,
            rewrite_mode=rewrite_mode,
            rerank_mode=rerank_mode,
            sim_threshold=sim_threshold,
            k_before=k_before,
            k_after=k_after,
            filtered_out=filtered_out,
            answer_override=(
                "По индексу этого репозитория не видно пересечения значимых слов вопроса с найденными фрагментами кода. "
                "Индекс описывает проект, а не произвольные темы; сформулируйте вопрос в терминах кода, API, файлов или компонентов."
            ),
            keyword_overlap_max=kw_max,
            keyword_overlap_required=min_kw,
            answer_min_score=min_for_answer,
        )
        payload["status"] = "dont_know"
        return payload

    sources = [
        {
            "chunk_id": c.chunk_id,
            "score": c.score,
            "rerank_score": c.rerank_score,
            "keyword_overlap": c.keyword_overlap,
            "file": c.meta.get("file", ""),
            "section": c.section,
            "strategy": c.strategy,
        }
        for c in chunks_after
    ]
    ctx_parts: list[str] = []
    used = 0
    for ch in chunks_after:
        block = (
            f"[SOURCE file={ch.meta.get('file','')} section={ch.section} chunk_id={ch.chunk_id} "
            f"score={ch.score:.4f} rerank={ch.rerank_score:.4f}]\n{ch.text}\n"
        )
        if used + len(block) > max_context_chars:
            break
        ctx_parts.append(block)
        used += len(block)
    context = "\n\n".join(ctx_parts).strip()
    return {
        "status": "ok",
        "query_original": query_original,
        "query_rewritten": query_rewritten,
        "chunks_after": chunks_after,
        "sources": sources,
        "context": context,
        "filtered_out": filtered_out,
        "retrieved_before_count": len(chunks_before),
        "retrieved_count": len(chunks_after),
        "rewrite_mode": rewrite_mode,
        "rerank_mode": rerank_mode,
        "sim_threshold": sim_threshold,
        "answer_min_score": min_for_answer,
        "top_k_before": k_before,
        "top_k_after": k_after,
        "relevance_max_score": max_score,
        "relevance_threshold": min_for_answer,
    }


def answer_without_rag(question: str) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": "You are a concise technical assistant. Answer in Russian."},
        {"role": "user", "content": question},
    ]
    try:
        ans = _call_llm(messages)
        return {"mode": "without_rag", "answer": ans, "sources": []}
    except Exception as e:
        return {
            "mode": "without_rag",
            "answer": f"LLM вызов не удался: {e}",
            "sources": [],
            "fallback": True,
        }


def answer_with_rag(
    question: str,
    *,
    db_path: Path,
    strategy: str = "structured",
    top_k: int = 5,
    max_context_chars: int = 6000,
    rewrite_mode: str = "none",
    rerank_mode: str = "none",
    top_k_before: int | None = None,
    top_k_after: int | None = None,
    sim_threshold: float = 0.12,
    answer_min_score: float | None = None,
) -> dict[str, Any]:
    prep = prepare_rag_context(
        question,
        db_path=db_path,
        strategy=strategy,
        top_k=top_k,
        max_context_chars=max_context_chars,
        rewrite_mode=rewrite_mode,
        rerank_mode=rerank_mode,
        top_k_before=top_k_before,
        top_k_after=top_k_after,
        sim_threshold=sim_threshold,
        answer_min_score=answer_min_score,
    )
    if prep.get("status") == "dont_know":
        out = {k: v for k, v in prep.items() if k != "status"}
        return out

    query_original = str(prep["query_original"])
    query_rewritten = str(prep["query_rewritten"])
    chunks_after: list[RetrievedChunk] = prep["chunks_after"]  # type: ignore[assignment]
    sources = prep["sources"]
    context = str(prep["context"])
    filtered_out = prep["filtered_out"]
    k_before = int(prep["top_k_before"])
    k_after = int(prep["top_k_after"])
    min_for_answer = float(prep["answer_min_score"])
    max_score = float(prep["relevance_max_score"])

    schema_hint = (
        '{"answer":"краткий ответ на русском",'
        '"quotes":[{"chunk_id":"<id из контекста>","text":"дословная цитата из того же чанка, до ~400 символов"}]}'
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Ты технический ассистент. Отвечай по-русски только на основе контекста. "
                "Верни ТОЛЬКО один JSON-объект без markdown и без пояснений. Схема: "
                f"{schema_hint} "
                "Поля quotes обязательны: одна или несколько дословных подстрок из соответствующих чанков; "
                "chunk_id должен совпадать с chunk_id из контекста. Не выдумывай факты и не подставляй текст не из контекста."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Вопрос:\n{query_original}\n\n"
                f"Контекст:\n{context}\n\n"
                "Сформируй JSON с полями answer и quotes; цитаты — только из текста контекста выше."
            ),
        },
    ]
    payload: dict[str, Any] = {
        "mode": "with_rag",
        "answer": "",
        "sources": sources,
        "quotes": [],
        "dont_know": False,
        "relevance_max_score": max_score,
        "relevance_threshold": min_for_answer,
        "retrieved_before_count": int(prep["retrieved_before_count"]),
        "retrieved_count": len(chunks_after),
        "query_original": query_original,
        "query_rewritten": query_rewritten,
        "rewrite_mode": rewrite_mode,
        "rerank_mode": rerank_mode,
        "sim_threshold": sim_threshold,
        "answer_min_score": min_for_answer,
        "top_k_before": k_before,
        "top_k_after": k_after,
        "filtered_out": filtered_out,
    }
    try:
        raw = _call_llm(messages, json_object=True)
        parsed = _parse_json_object(raw) or {}
        ans = _merge_llm_answer(parsed)
        if not ans:
            ans = "По приведённым фрагментам данных недостаточно для полного ответа."
        payload["answer"] = ans
        payload["quotes"] = _ensure_quotes(parsed, chunks_after)
    except Exception:
        ans, quotes = _structured_fallback_answer(query_original, chunks_after)
        payload["answer"] = ans
        payload["quotes"] = quotes
        payload["fallback"] = True
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG QA: compare modes with and without retrieval.")
    p.add_argument("--question", required=True)
    p.add_argument("--mode", choices=["without_rag", "with_rag", "both"], default="both")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--strategy", choices=["fixed", "structured", "all"], default="structured")
    p.add_argument("--top-k", type=int, default=5, help="Legacy alias for top-k after rerank/filter")
    p.add_argument("--top-k-before", type=int, default=20)
    p.add_argument("--top-k-after", type=int, default=5)
    p.add_argument("--sim-threshold", type=float, default=0.12)
    p.add_argument(
        "--answer-min-score",
        type=float,
        default=None,
        help="Мин. embedding score лучшего чанка; ниже — ответ «не знаю» (по умолчанию: RAG_ANSWER_MIN_SCORE или sim-threshold).",
    )
    p.add_argument("--rerank-mode", choices=["none", "threshold", "hybrid"], default="hybrid")
    p.add_argument("--rewrite-mode", choices=["none", "heuristic"], default="heuristic")
    p.add_argument("--max-context-chars", type=int, default=6000)
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    db_path = (root / args.db_path).resolve()
    question = args.question.strip()
    if not question:
        raise SystemExit("Question is empty.")
    out: dict[str, Any] = {"question": question}
    if args.mode in ("without_rag", "both"):
        out["without_rag"] = answer_without_rag(question)
    if args.mode in ("with_rag", "both"):
        out["with_rag"] = answer_with_rag(
            question,
            db_path=db_path,
            strategy=args.strategy,
            top_k=max(1, args.top_k),
            top_k_before=max(1, args.top_k_before),
            top_k_after=max(1, args.top_k_after),
            sim_threshold=float(args.sim_threshold),
            answer_min_score=args.answer_min_score,
            rewrite_mode=args.rewrite_mode,
            rerank_mode=args.rerank_mode,
            max_context_chars=max(800, args.max_context_chars),
        )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"Question: {question}\n")
        if "without_rag" in out:
            print("=== WITHOUT RAG ===")
            print(out["without_rag"]["answer"])
            print()
        if "with_rag" in out:
            rag = out["with_rag"]
            print("=== WITH RAG ===")
            print(
                f"(rewrite={rag.get('rewrite_mode')} | rerank={rag.get('rerank_mode')} | "
                f"k_before={rag.get('top_k_before')} -> k_after={rag.get('top_k_after')} | "
                f"threshold={rag.get('sim_threshold')})"
            )
            print(f"Query rewritten: {rag.get('query_rewritten')}")
            print(rag["answer"])
            print()
            if rag.get("dont_know"):
                print(
                    f"(dont_know: {rag.get('dont_know_reason')} | "
                    f"max_score={rag.get('relevance_max_score')} < threshold={rag.get('relevance_threshold')})"
                )
                print()
            srcs = rag.get("sources", [])
            if srcs:
                print("Sources:")
                for s in srcs:
                    print(
                        f"- score={s['score']:.4f} rerank={s['rerank_score']:.4f} "
                        f"file={s['file']} section={s['section']} chunk_id={s['chunk_id']}"
                    )
            qs = rag.get("quotes") or []
            if qs:
                print()
                print("Quotes:")
                for q in qs:
                    tid = q.get("chunk_id", "")
                    tx = str(q.get("text", "")).replace("\n", " ")[:200]
                    print(f"- chunk_id={tid}: {tx}…")


if __name__ == "__main__":
    main()
