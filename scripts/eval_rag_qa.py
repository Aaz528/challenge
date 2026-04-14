#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_qa import answer_with_rag, answer_without_rag


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run 10 control questions: without RAG vs with RAG.")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--questions-path", default="docs/rag_control_questions.json")
    p.add_argument("--report-path", default="docs/rag_vs_no_rag_report.md")
    p.add_argument("--strategy", choices=["fixed", "structured", "all"], default="structured")
    p.add_argument("--top-k", type=int, default=5)
    return p.parse_args()


def _contains_expectation(answer: str, expectation: str) -> bool:
    words = [w.lower() for w in expectation.split() if len(w) >= 6][:4]
    if not words:
        return False
    ans = answer.lower()
    return any(w in ans for w in words)


def _source_match(found_sources: list[str], expected_sources: list[str]) -> bool:
    found = " ".join(found_sources).lower()
    return any((src.lower() in found) for src in expected_sources)


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

    lines: list[str] = []
    lines.append("# RAG vs No-RAG Quality Comparison")
    lines.append("")
    lines.append(f"- Questions file: `{questions_path}`")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- Retrieval strategy: `{args.strategy}`")
    lines.append(f"- Top-k: `{args.top_k}`")
    lines.append("")

    score_no = 0
    score_rag = 0
    source_hits = 0

    for i, row in enumerate(payload, start=1):
        qid = str(row.get("id", f"q{i:02d}"))
        question = str(row.get("question", "")).strip()
        expectation = str(row.get("expectation", "")).strip()
        expected_sources = [str(x) for x in row.get("expected_sources", [])]
        if not question:
            continue

        no_rag = answer_without_rag(question)
        with_rag = answer_with_rag(
            question,
            db_path=db_path,
            strategy=args.strategy,
            top_k=args.top_k,
            max_context_chars=6500,
        )

        no_answer = str(no_rag.get("answer", ""))
        rag_answer = str(with_rag.get("answer", ""))
        rag_sources = [str(s.get("file", "")) for s in with_rag.get("sources", [])]

        no_ok = _contains_expectation(no_answer, expectation)
        rag_ok = _contains_expectation(rag_answer, expectation)
        src_ok = _source_match(rag_sources, expected_sources)
        score_no += 1 if no_ok else 0
        score_rag += 1 if rag_ok else 0
        source_hits += 1 if src_ok else 0

        lines.append(f"## {qid}: {question}")
        lines.append("")
        lines.append(f"**Ожидание:** {expectation}")
        lines.append("")
        lines.append("**Ожидаемые источники:**")
        for src in expected_sources:
            lines.append(f"- `{src}`")
        lines.append("")
        lines.append("**Ответ без RAG**")
        lines.append("")
        lines.append(no_answer)
        lines.append("")
        lines.append("**Ответ с RAG**")
        lines.append("")
        lines.append(rag_answer)
        lines.append("")
        lines.append("**Источники (retrieval)**")
        for s in with_rag.get("sources", []):
            lines.append(
                f"- score={float(s.get('score', 0.0)):.4f} file=`{s.get('file','')}` section=`{s.get('section','')}` chunk_id=`{s.get('chunk_id','')}`"
            )
        lines.append("")
        lines.append(
            f"**Автооценка:** expectation_match(no_rag)={no_ok}, expectation_match(with_rag)={rag_ok}, source_match(with_rag)={src_ok}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

    total = len(payload)
    lines.insert(
        6,
        f"- Auto scores: no_rag={score_no}/{total}, with_rag={score_rag}/{total}, source_match={source_hits}/{total}",
    )
    if score_rag > score_no:
        conclusion = "RAG-режим показывает лучший результат по авто-проверке ожиданий."
    elif score_rag < score_no:
        conclusion = "No-RAG режим по авто-проверке оказался не хуже или лучше; проверьте retrieval/prompts."
    else:
        conclusion = "Оба режима дали сопоставимый авто-результат; вероятно нужен более строгий benchmark."
    lines.insert(7, f"- Auto conclusion: {conclusion}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {report_path}")
    print(f"Scores: no_rag={score_no}/{total}, with_rag={score_rag}/{total}, source_match={source_hits}/{total}")


if __name__ == "__main__":
    main()
