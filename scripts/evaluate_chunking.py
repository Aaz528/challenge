#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from rag_index_lib import Embedder, cosine_similarity


QUERIES = [
    "Где в проекте выполняется маршрутизация вызовов MCP инструментов?",
    "Как устроен потоковый ответ ассистента через SSE?",
    "Где читаются MCP настройки из .env?",
    "Как реализован function calling у LLM агента?",
    "Где определяется API endpoint для погоды Иркутска?",
    "Где хранится и обновляется рабочая память ветки?",
    "Как устроен список и ping MCP серверов?",
    "Где в фронтенде вызывается weather popup?",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare fixed vs structured chunking on local index.")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--report-path", default="docs/rag_chunking_comparison.md")
    return p.parse_args()


def _load_strategy_rows(conn: sqlite3.Connection, strategy: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.chunk_id, c.section, c.text, c.metadata_json, e.vector_json
        FROM chunks c
        JOIN embeddings e ON e.chunk_row_id = c.id
        WHERE c.strategy = ?
        ORDER BY c.id
        """,
        (strategy,),
    ).fetchall()
    out: list[dict] = []
    for chunk_id, section, text, metadata_json, vector_json in rows:
        out.append(
            {
                "chunk_id": str(chunk_id),
                "section": str(section),
                "text": str(text),
                "meta": json.loads(str(metadata_json)),
                "vector": [float(x) for x in json.loads(str(vector_json))],
            }
        )
    return out


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    db_path = (root / args.db_path).resolve()
    report_path = (root / args.report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    fixed_rows = _load_strategy_rows(conn, "fixed")
    structured_rows = _load_strategy_rows(conn, "structured")
    conn.close()
    if not fixed_rows or not structured_rows:
        raise SystemExit("Both strategies must be indexed first (fixed and structured).")

    embedder = Embedder()
    lines: list[str] = []
    lines.append("# RAG Chunking Comparison")
    lines.append("")
    lines.append(f"- Database: `{db_path}`")
    lines.append(f"- Query count: {len(QUERIES)}")
    lines.append(f"- Top-k: {args.top_k}")
    lines.append(f"- Query embedding model: `{embedder.model_name}`")
    lines.append("")
    lines.append("## Corpus Stats")
    lines.append("")
    lines.append(f"- Fixed chunks: {len(fixed_rows)}")
    lines.append(f"- Structured chunks: {len(structured_rows)}")
    lines.append("")
    lines.append("## Retrieval Side-by-Side")
    lines.append("")

    fixed_sum = 0.0
    structured_sum = 0.0
    for i, q in enumerate(QUERIES, start=1):
        q_vec = embedder.embed_query(q)
        fixed_scored = [
            (cosine_similarity(q_vec, row["vector"]), row) for row in fixed_rows
        ]
        structured_scored = [
            (cosine_similarity(q_vec, row["vector"]), row) for row in structured_rows
        ]
        fixed_scored.sort(key=lambda x: x[0], reverse=True)
        structured_scored.sort(key=lambda x: x[0], reverse=True)
        best_f = fixed_scored[: args.top_k]
        best_s = structured_scored[: args.top_k]
        fixed_sum += best_f[0][0] if best_f else 0.0
        structured_sum += best_s[0][0] if best_s else 0.0

        lines.append(f"### Query {i}")
        lines.append("")
        lines.append(f"`{q}`")
        lines.append("")
        lines.append("**Fixed-size top hits**")
        for score, row in best_f:
            lines.append(
                f"- score={score:.4f} | file=`{row['meta'].get('file','')}` | section=`{row['section']}` | chunk_id=`{row['chunk_id']}`"
            )
        lines.append("")
        lines.append("**Structured top hits**")
        for score, row in best_s:
            lines.append(
                f"- score={score:.4f} | file=`{row['meta'].get('file','')}` | section=`{row['section']}` | chunk_id=`{row['chunk_id']}`"
            )
        lines.append("")

    lines.append("## Quick Summary")
    lines.append("")
    avg_fixed = fixed_sum / len(QUERIES)
    avg_structured = structured_sum / len(QUERIES)
    lines.append(f"- Avg best-score fixed: `{avg_fixed:.4f}`")
    lines.append(f"- Avg best-score structured: `{avg_structured:.4f}`")
    lines.append("- Structured strategy usually gives more interpretable `section` metadata.")
    lines.append("- Fixed strategy often yields more uniform chunk lengths and simpler tuning.")
    lines.append("")
    lines.append("## Auto Conclusion")
    lines.append("")
    if avg_structured > avg_fixed + 0.01:
        lines.append(
            "- По средней top-1 схожести structured выглядит предпочтительнее на текущем корпусе."
        )
    elif avg_fixed > avg_structured + 0.01:
        lines.append(
            "- По средней top-1 схожести fixed выглядит предпочтительнее на текущем корпусе."
        )
    else:
        lines.append(
            "- По средней top-1 схожести стратегии близки; выбор лучше делать по интерпретируемости и размеру индекса."
        )
    lines.append(
        "- Для кода structured обычно удобнее для объяснимости (section = class/def), fixed проще и стабильнее в настройке."
    )
    lines.append("")
    lines.append("## Manual Conclusion Template")
    lines.append("")
    lines.append("- Где fixed оказался лучше: ...")
    lines.append("- Где structured оказался лучше: ...")
    lines.append("- Что выбрано как дефолт и почему: ...")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {report_path}")


if __name__ == "__main__":
    main()
