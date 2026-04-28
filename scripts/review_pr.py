#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from rag_qa import answer_with_rag
from rag_index_lib import iter_default_corpus


def _run(cmd: list[str], cwd: Path) -> str:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip() or f"command failed: {' '.join(cmd)}")
    return p.stdout


def _git_changed_files(root: Path, base: str, head: str) -> list[str]:
    out = _run(["git", "diff", "--name-only", f"{base}...{head}"], root)
    return [x.strip() for x in out.splitlines() if x.strip()]


def _git_diff(root: Path, base: str, head: str, max_chars: int) -> str:
    out = _run(["git", "diff", "--no-color", f"{base}...{head}"], root)
    if len(out) > max_chars:
        return out[: max_chars - 1] + "…"
    return out


def _build_prompt(section: str, changed_files: list[str], diff_text: str) -> str:
    files_block = "\n".join(f"- {f}" for f in changed_files[:200]) or "- (none)"
    return (
        "Сделай code review изменения PR в этом проекте.\n"
        f"Нужен раздел: {section}\n\n"
        f"Изменённые файлы:\n{files_block}\n\n"
        "Ниже git diff PR:\n"
        f"{diff_text}\n\n"
        "Дай конкретные замечания, привязывай их к файлам/фрагментам изменений. "
        "Если критичных проблем нет, так и напиши."
    )


def _review_section(question: str, root: Path) -> dict:
    return answer_with_rag(
        question,
        db_path=root / "rag_index.db",
        strategy="structured",
        rewrite_mode="heuristic",
        rerank_mode="hybrid",
        top_k_before=24,
        top_k_after=8,
        sim_threshold=0.10,
        max_context_chars=9000,
    )


def _render_report(
    *,
    base: str,
    head: str,
    changed_files: list[str],
    bugs: dict,
    arch: dict,
    recs: dict,
) -> str:
    lines: list[str] = []
    lines.append("# PR Review (Assistant + RAG)")
    lines.append("")
    lines.append(f"- Range: `{base}...{head}`")
    lines.append(f"- Changed files: **{len(changed_files)}**")
    lines.append("")
    lines.append("## Потенциальные баги")
    lines.append("")
    lines.append(str(bugs.get("answer", "")).strip() or "Нет данных.")
    lines.append("")
    lines.append("## Архитектурные проблемы")
    lines.append("")
    lines.append(str(arch.get("answer", "")).strip() or "Нет данных.")
    lines.append("")
    lines.append("## Рекомендации")
    lines.append("")
    lines.append(str(recs.get("answer", "")).strip() or "Нет данных.")
    lines.append("")
    lines.append("## Источники (RAG)")
    lines.append("")
    for title, payload in (
        ("Баги", bugs),
        ("Архитектура", arch),
        ("Рекомендации", recs),
    ):
        lines.append(f"### {title}")
        srcs = payload.get("sources") or []
        if not srcs:
            lines.append("- (нет источников)")
            continue
        for s in srcs[:12]:
            lines.append(
                f"- `{s.get('file','')}` | `{s.get('section','')}` | chunk_id=`{s.get('chunk_id','')}`"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate PR review text using RAG over project code/docs.")
    p.add_argument("--base", required=True, help="Base commit/branch for git diff range")
    p.add_argument("--head", required=True, help="Head commit/branch for git diff range")
    p.add_argument("--output", default="artifacts/pr_review.md")
    p.add_argument("--json-output", default="artifacts/pr_review.json")
    p.add_argument("--max-diff-chars", type=int, default=40000)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent

    changed = _git_changed_files(root, args.base, args.head)
    if not changed:
        report = "# PR Review (Assistant + RAG)\n\nНет изменённых файлов.\n"
        out = root / args.output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Report written: {out}")
        return

    diff_text = _git_diff(root, args.base, args.head, args.max_diff_chars)
    bugs = _review_section(_build_prompt("потенциальные баги", changed, diff_text), root)
    arch = _review_section(_build_prompt("архитектурные проблемы", changed, diff_text), root)
    recs = _review_section(_build_prompt("рекомендации по улучшению", changed, diff_text), root)

    report = _render_report(
        base=args.base,
        head=args.head,
        changed_files=changed,
        bugs=bugs,
        arch=arch,
        recs=recs,
    )
    out = root / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    raw = {
        "base": args.base,
        "head": args.head,
        "changed_files": changed,
        "bugs": bugs,
        "architecture": arch,
        "recommendations": recs,
        "default_corpus_files": [str(p) for p in iter_default_corpus(root)],
    }
    jout = root / args.json_output
    jout.parent.mkdir(parents=True, exist_ok=True)
    jout.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Report written: {out}")
    print(f"JSON written: {jout}")


if __name__ == "__main__":
    main()
