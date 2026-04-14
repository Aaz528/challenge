#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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


def _load_chunks(db_path: Path, strategy: str) -> list[tuple[str, str, str, str, str]]:
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
    return [(str(a), str(b), str(c), str(d), str(e)) for a, b, c, d, e, _ in rows]


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
            f"{i}) [{ch.meta.get('file', '')}] {ch.section} (score={ch.score:.4f}): {snippet}"
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
) -> dict[str, Any]:
    chunks = _retrieve(db_path, question, strategy=strategy, top_k=top_k)
    sources = [
        {
            "chunk_id": c.chunk_id,
            "score": c.score,
            "file": c.meta.get("file", ""),
            "section": c.section,
            "strategy": c.strategy,
        }
        for c in chunks
    ]
    ctx_parts: list[str] = []
    used = 0
    for ch in chunks:
        block = (
            f"[SOURCE file={ch.meta.get('file','')} section={ch.section} chunk_id={ch.chunk_id} score={ch.score:.4f}]\n"
            f"{ch.text}\n"
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
                f"Вопрос:\n{question}\n\n"
                f"Контекст:\n{context}\n\n"
                "Сформируй ответ и коротко укажи, на какие источники ты опирался."
            ),
        },
    ]
    try:
        ans = _call_llm(messages)
        return {"mode": "with_rag", "answer": ans, "sources": sources, "retrieved_count": len(chunks)}
    except Exception:
        return {
            "mode": "with_rag",
            "answer": _fallback_answer(question, chunks),
            "sources": sources,
            "retrieved_count": len(chunks),
            "fallback": True,
        }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG QA: compare modes with and without retrieval.")
    p.add_argument("--question", required=True)
    p.add_argument("--mode", choices=["without_rag", "with_rag", "both"], default="both")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--strategy", choices=["fixed", "structured", "all"], default="structured")
    p.add_argument("--top-k", type=int, default=5)
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
            top_k=args.top_k,
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
            print("=== WITH RAG ===")
            print(out["with_rag"]["answer"])
            print()
            srcs = out["with_rag"].get("sources", [])
            if srcs:
                print("Sources:")
                for s in srcs:
                    print(
                        f"- score={s['score']:.4f} file={s['file']} section={s['section']} chunk_id={s['chunk_id']}"
                    )


if __name__ == "__main__":
    main()
