#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_qa import answer_with_rag, answer_without_rag


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run 10 control questions and compare baseline RAG vs improved RAG.")
    p.add_argument("--db-path", default="rag_index.db")
    p.add_argument("--questions-path", default="docs/rag_control_questions.json")
    p.add_argument("--report-path", default="docs/rag_rerank_comparison.md")
    p.add_argument("--strategy", choices=["fixed", "structured", "all"], default="structured")
    p.add_argument("--top-k-before", type=int, default=20)
    p.add_argument("--top-k-after", type=int, default=5)
    p.add_argument("--sim-threshold", type=float, default=0.12)
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
    lines.append("# RAG Rerank/Filter Comparison")
    lines.append("")
    lines.append(f"- Questions file: `{questions_path}`")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- Retrieval strategy: `{args.strategy}`")
    lines.append(
        f"- Baseline profile: rewrite=none, rerank=none, top_k_before={args.top_k_before}, top_k_after={args.top_k_after}"
    )
    lines.append(
        f"- Improved profile: rewrite=heuristic, rerank=hybrid, top_k_before={args.top_k_before}, top_k_after={args.top_k_after}, sim_threshold={args.sim_threshold}"
    )
    lines.append("")

    score_no = 0
    score_base = 0
    score_improved = 0
    source_hits_base = 0
    source_hits_improved = 0
    kept_base = 0
    kept_improved = 0

    for i, row in enumerate(payload, start=1):
        qid = str(row.get("id", f"q{i:02d}"))
        question = str(row.get("question", "")).strip()
        expectation = str(row.get("expectation", "")).strip()
        expected_sources = [str(x) for x in row.get("expected_sources", [])]
        if not question:
            continue

        no_rag = answer_without_rag(question)
        rag_base = answer_with_rag(
            question,
            db_path=db_path,
            strategy=args.strategy,
            top_k=args.top_k_after,
            top_k_before=args.top_k_before,
            top_k_after=args.top_k_after,
            rewrite_mode="none",
            rerank_mode="none",
            sim_threshold=0.0,
            max_context_chars=6500,
        )
        rag_improved = answer_with_rag(
            question,
            db_path=db_path,
            strategy=args.strategy,
            top_k=args.top_k_after,
            top_k_before=args.top_k_before,
            top_k_after=args.top_k_after,
            rewrite_mode="heuristic",
            rerank_mode="hybrid",
            sim_threshold=args.sim_threshold,
            max_context_chars=6500,
        )

        no_answer = str(no_rag.get("answer", ""))
        base_answer = str(rag_base.get("answer", ""))
        improved_answer = str(rag_improved.get("answer", ""))
        base_sources = [str(s.get("file", "")) for s in rag_base.get("sources", [])]
        improved_sources = [str(s.get("file", "")) for s in rag_improved.get("sources", [])]

        no_ok = _contains_expectation(no_answer, expectation)
        base_ok = _contains_expectation(base_answer, expectation)
        improved_ok = _contains_expectation(improved_answer, expectation)
        src_base_ok = _source_match(base_sources, expected_sources)
        src_improved_ok = _source_match(improved_sources, expected_sources)
        score_no += 1 if no_ok else 0
        score_base += 1 if base_ok else 0
        score_improved += 1 if improved_ok else 0
        source_hits_base += 1 if src_base_ok else 0
        source_hits_improved += 1 if src_improved_ok else 0
        kept_base += int(rag_base.get("retrieved_count", 0))
        kept_improved += int(rag_improved.get("retrieved_count", 0))

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
        lines.append("**Ответ с RAG (baseline: без rewrite/filter)**")
        lines.append("")
        lines.append(base_answer)
        lines.append("")
        lines.append("**Источники baseline**")
        for s in rag_base.get("sources", []):
            lines.append(
                f"- score={float(s.get('score', 0.0)):.4f} file=`{s.get('file','')}` section=`{s.get('section','')}` chunk_id=`{s.get('chunk_id','')}`"
            )
        lines.append("")
        lines.append("**Ответ с RAG (improved: rewrite + rerank/filter)**")
        lines.append("")
        lines.append(improved_answer)
        lines.append("")
        lines.append("**Источники improved**")
        for s in rag_improved.get("sources", []):
            lines.append(
                f"- score={float(s.get('score', 0.0)):.4f} rerank={float(s.get('rerank_score', 0.0)):.4f} "
                f"file=`{s.get('file','')}` section=`{s.get('section','')}` chunk_id=`{s.get('chunk_id','')}`"
            )
        lines.append("")
        if rag_improved.get("filtered_out"):
            lines.append("**Filtered out (improved)**")
            for s in rag_improved.get("filtered_out", [])[:5]:
                lines.append(
                    f"- score={float(s.get('score', 0.0)):.4f} file=`{s.get('file','')}` section=`{s.get('section','')}` chunk_id=`{s.get('chunk_id','')}`"
                )
            lines.append("")
        lines.append(
            f"**Автооценка:** expectation(no_rag)={no_ok}, expectation(baseline)={base_ok}, expectation(improved)={improved_ok}, "
            f"source_match(baseline)={src_base_ok}, source_match(improved)={src_improved_ok}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

    total = len(payload)
    lines.insert(
        8,
        (
            f"- Auto scores: no_rag={score_no}/{total}, baseline_rag={score_base}/{total}, "
            f"improved_rag={score_improved}/{total}, source_match_baseline={source_hits_base}/{total}, "
            f"source_match_improved={source_hits_improved}/{total}"
        ),
    )
    lines.insert(
        9,
        f"- Avg kept chunks: baseline={kept_base / max(total,1):.2f}, improved={kept_improved / max(total,1):.2f}",
    )
    if score_improved > score_base:
        conclusion = "Режим с rewrite + rerank/filter показывает лучший результат по авто-проверке ожиданий."
    elif score_improved < score_base:
        conclusion = "Baseline оказался не хуже improved; подберите threshold/top-k или ослабьте фильтр."
    else:
        conclusion = "Baseline и improved дали сопоставимый авто-результат; нужен более строгий benchmark."
    lines.insert(10, f"- Auto conclusion: {conclusion}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {report_path}")
    print(
        "Scores: "
        f"no_rag={score_no}/{total}, baseline_rag={score_base}/{total}, improved_rag={score_improved}/{total}, "
        f"source_match_baseline={source_hits_base}/{total}, source_match_improved={source_hits_improved}/{total}"
    )


if __name__ == "__main__":
    main()
