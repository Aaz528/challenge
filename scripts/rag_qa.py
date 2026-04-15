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


def _call_llm(messages: list[dict[str, str]]) -> str:
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
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 900,
        },
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    data = resp.json()
    text = str(data["choices"][0]["message"]["content"]).strip()
    if not text:
        raise RuntimeError("LLM returned empty text")
    return text


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


def _fallback_answer(question: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return (
            "Локальный fallback-ответ: не удалось вызвать LLM и не найдены релевантные чанки в индексе. "
            f"Вопрос: {question}"
        )
    lines = [
        "Локальный fallback-ответ (LLM недоступен):",
        f"Вопрос: {question}",
        "",
        "Релевантные фрагменты:",
    ]
    for i, ch in enumerate(chunks[:5], start=1):
        snippet = ch.text.replace("\n", " ")[:220]
        lines.append(
            f"{i}) [{ch.meta.get('file', '')}] {ch.section} (score={ch.score:.4f}, rerank={ch.rerank_score:.4f}): {snippet}"
        )
    return "\n".join(lines)


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
) -> dict[str, Any]:
    query_original = question.strip()
    query_rewritten = _rewrite_query(query_original, rewrite_mode)
    k_before = max(1, int(top_k_before if top_k_before is not None else max(top_k, 12)))
    k_after = max(1, int(top_k_after if top_k_after is not None else top_k))
    chunks_before = _retrieve(db_path, query_rewritten, strategy=strategy, top_k=k_before)
    chunks_after, removed = _rerank_and_filter(
        query_rewritten,
        chunks_before,
        rerank_mode=rerank_mode,
        sim_threshold=sim_threshold,
        top_k_after=k_after,
    )
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
    filtered_out = [
        {
            "chunk_id": c.chunk_id,
            "score": c.score,
            "file": c.meta.get("file", ""),
            "section": c.section,
        }
        for c in removed[:20]
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
    messages = [
        {
            "role": "system",
            "content": (
                "Ты технический ассистент. Отвечай по-русски. "
                "Используй контекст из источников ниже. Если в контексте не хватает данных, скажи об этом явно. "
                "Не выдумывай факты."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Вопрос:\n{query_original}\n\n"
                f"Контекст:\n{context}\n\n"
                "Сформируй ответ и коротко укажи, на какие источники ты опирался."
            ),
        },
    ]
    payload = {
        "mode": "with_rag",
        "answer": "",
        "sources": sources,
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
    try:
        payload["answer"] = _call_llm(messages)
        return payload
    except Exception:
        payload["answer"] = _fallback_answer(query_original, chunks_after)
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
            srcs = rag.get("sources", [])
            if srcs:
                print("Sources:")
                for s in srcs:
                    print(
                        f"- score={s['score']:.4f} rerank={s['rerank_score']:.4f} "
                        f"file={s['file']} section={s['section']} chunk_id={s['chunk_id']}"
                    )


if __name__ == "__main__":
    main()
