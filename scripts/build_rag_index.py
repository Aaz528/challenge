#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_index_lib import (
    Embedder,
    ensure_schema,
    estimate_tokens,
    iter_default_corpus,
    load_document,
    make_chunks,
    open_db,
    reset_index,
    utc_now_iso,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build local RAG index in SQLite.")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument(
        "--strategy",
        default="both",
        choices=["fixed", "structured", "both"],
        help="Chunking strategy to run.",
    )
    p.add_argument("--chunk-size", type=int, default=1200)
    p.add_argument("--overlap", type=int, default=200)
    p.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing index before insert.",
    )
    p.add_argument(
        "--files",
        nargs="*",
        default=[],
        help="Optional explicit file paths. If omitted, default project corpus is used.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    db_path = (root / args.db_path).resolve()
    files = [Path(f).resolve() for f in args.files] if args.files else list(iter_default_corpus(root))
    if not files:
        raise SystemExit("No files found for indexing.")

    strategies = ["fixed", "structured"] if args.strategy == "both" else [args.strategy]
    embedder = Embedder()
    conn = open_db(db_path)
    ensure_schema(conn)
    if args.reset:
        reset_index(conn)

    inserted_docs = 0
    inserted_chunks = 0
    for fp in files:
        doc = load_document(fp)
        cur = conn.execute(
            """
            INSERT INTO documents(source, title, file_path, content_hash, total_chars, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                doc.source,
                doc.title,
                doc.file_path,
                doc.content_hash,
                len(doc.text),
                utc_now_iso(),
            ),
        )
        doc_id = int(cur.lastrowid)
        inserted_docs += 1

        for strategy in strategies:
            chunks = make_chunks(
                doc,
                strategy=strategy,
                chunk_size=args.chunk_size,
                overlap=args.overlap,
            )
            if not chunks:
                continue
            vectors = embedder.embed_texts([c.text for c in chunks])
            for chunk, vec in zip(chunks, vectors):
                row = conn.execute(
                    """
                    INSERT INTO chunks(
                        document_id, strategy, chunk_id, section, chunk_index, text,
                        char_count, token_estimate, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        strategy,
                        chunk.chunk_id,
                        chunk.section,
                        chunk.chunk_index,
                        chunk.text,
                        len(chunk.text),
                        estimate_tokens(chunk.text),
                        json.dumps(chunk.metadata, ensure_ascii=False),
                    ),
                )
                chunk_row_id = int(row.lastrowid)
                conn.execute(
                    """
                    INSERT INTO embeddings(chunk_row_id, model, dim, vector_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        chunk_row_id,
                        embedder.model_name,
                        len(vec),
                        json.dumps(vec, ensure_ascii=False),
                    ),
                )
                inserted_chunks += 1

    conn.commit()
    stat = conn.execute(
        """
        SELECT strategy, COUNT(*), AVG(char_count), AVG(token_estimate)
        FROM chunks
        GROUP BY strategy
        ORDER BY strategy
        """
    ).fetchall()
    conn.close()

    print(f"Indexed documents: {inserted_docs}")
    print(f"Indexed chunks: {inserted_chunks}")
    print(f"Embedding model: {embedder.model_name}")
    print(f"SQLite: {db_path}")
    for strategy, cnt, avg_chars, avg_tok in stat:
        print(
            f"- {strategy}: chunks={cnt}, avg_chars={avg_chars:.1f}, avg_tokens={avg_tok:.1f}"
        )


if __name__ == "__main__":
    main()
