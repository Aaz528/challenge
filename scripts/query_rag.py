#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from rag_index_lib import Embedder, cosine_similarity


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Query local RAG index by semantic similarity.")
    p.add_argument("query", help="User query for retrieval")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--strategy", choices=["fixed", "structured", "all"], default="all")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--show-text-chars", type=int, default=280)
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    db_path = (root / args.db_path).resolve()
    conn = sqlite3.connect(str(db_path))
    if args.strategy == "all":
        where = ""
        params: tuple[object, ...] = ()
    else:
        where = "WHERE c.strategy = ?"
        params = (args.strategy,)
    rows = conn.execute(
        f"""
        SELECT c.strategy, c.chunk_id, c.section, c.text, c.metadata_json, e.vector_json
        FROM chunks c
        JOIN embeddings e ON e.chunk_row_id = c.id
        {where}
        ORDER BY c.id
        """
        ,
        params,
    ).fetchall()
    conn.close()
    if not rows:
        raise SystemExit("No indexed chunks found. Build index first.")

    embedder = Embedder()
    qv = embedder.embed_query(args.query)
    scored: list[tuple[float, dict]] = []
    for strategy, chunk_id, section, text, metadata_json, vector_json in rows:
        vec = [float(x) for x in json.loads(str(vector_json))]
        score = cosine_similarity(qv, vec)
        meta = json.loads(str(metadata_json))
        scored.append(
            (
                score,
                {
                    "strategy": str(strategy),
                    "chunk_id": str(chunk_id),
                    "section": str(section),
                    "text": str(text),
                    "meta": meta,
                },
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: max(1, args.top_k)]
    if args.json:
        payload = {
            "query": args.query,
            "embedding_model": embedder.model_name,
            "top_k": len(top),
            "results": [
                {
                    "rank": i,
                    "score": score,
                    "strategy": row["strategy"],
                    "chunk_id": row["chunk_id"],
                    "section": row["section"],
                    "meta": row["meta"],
                    "text_snippet": row["text"][: max(80, args.show_text_chars)],
                }
                for i, (score, row) in enumerate(top, start=1)
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"Query: {args.query}")
    print(f"Embedding model: {embedder.model_name}")
    print(f"Top-k: {len(top)}")
    for i, (score, row) in enumerate(top, start=1):
        snippet = row["text"][: max(80, args.show_text_chars)].replace("\n", " ")
        print("-" * 72)
        print(
            f"{i}. score={score:.4f} strategy={row['strategy']} file={row['meta'].get('file','')}"
        )
        print(f"   section={row['section']} chunk_id={row['chunk_id']}")
        print(f"   text={snippet}")


if __name__ == "__main__":
    main()
