#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_servers.file_assistant_mcp import analyzeFiles, readProjectFile, searchProject, writeProjectFile


def _parse_tool_json(raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"tool returned invalid JSON: {raw[:200]}") from e
    if not isinstance(obj, dict):
        raise RuntimeError("tool returned non-object JSON")
    return obj


def _write(path: str, content: str, *, overwrite: bool = True) -> None:
    root = _project_root()
    rp = Path(path)
    rel = rp.relative_to(root).as_posix() if rp.is_absolute() else rp.as_posix()
    out = _parse_tool_json(writeProjectFile(path=rel, content=content, overwrite=overwrite))
    if not out.get("ok"):
        raise RuntimeError(f"write failed for {path}: {out.get('error')}")


def _project_root() -> Path:
    return ROOT


def _run_cmd(root: Path, args: list[str]) -> str:
    p = subprocess.run(args, cwd=str(root), capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip() or f"command failed: {' '.join(args)}")
    return p.stdout


def scenario_find_api_usages() -> str:
    """
    Goal-level scenario:
    "Найти все места, где используются новые support/file-assistant API и подготовить отчёт."
    """
    patterns = [
        r"/api/support/ask",
        r"/api/mcp/file-assistant-demo",
        r"/api/mcp/project-git-demo",
    ]
    lines: list[str] = ["# Scenario 1: API Usage Map", ""]
    files_seen: set[str] = set()
    allowed_ext = (".py", ".ts", ".tsx", ".md", ".json", ".yml", ".yaml")
    for pat in patterns:
        raw = searchProject(pattern=pat, glob="", max_results=200)
        obj = _parse_tool_json(raw)
        matches = []
        for x in obj.get("matches", []):
            s = str(x)
            file_part = s.split(":", 1)[0]
            if file_part.startswith("artifacts/"):
                continue
            if file_part.endswith(allowed_ext):
                matches.append(s)
        matches = matches[:80]
        lines.append(f"## Pattern `{pat}`")
        lines.append("")
        if not matches:
            lines.append("- no matches")
            lines.append("")
            continue
        for m in matches:
            lines.append(f"- {m}")
            file_part = m.split(":", 1)[0]
            files_seen.add(file_part)
        lines.append("")
    lines.append(f"Files involved: **{len(files_seen)}**")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def scenario_check_file_invariants() -> str:
    """
    Goal-level scenario:
    "Проверить, что MCP servers соответствуют инвариантам структуры."
    """
    raw = searchProject(pattern=r"mcp\.server\.fastmcp|FastMCP\(", glob="mcp_servers/*.py", max_results=400)
    obj = _parse_tool_json(raw)
    all_hits = [str(x) for x in obj.get("matches", [])]
    files = sorted({h.split(":", 1)[0] for h in all_hits if ":" in h})

    report: list[str] = ["# Scenario 2: MCP File Invariants", ""]
    report.append("Инварианты:")
    report.append("- файл MCP-сервера должен содержать `mcp = FastMCP(`")
    report.append("- файл MCP-сервера должен содержать `if __name__ == \"__main__\":`")
    report.append("")

    checked = 0
    ok = 0
    for f in files:
        checked += 1
        content_obj = _parse_tool_json(readProjectFile(path=f, start_line=1, max_lines=5000))
        content = str(content_obj.get("content", ""))
        has_fastmcp = "mcp = FastMCP(" in content
        has_main = 'if __name__ == "__main__":' in content
        passed = has_fastmcp and has_main
        if passed:
            ok += 1
        report.append(
            f"- `{f}` -> {'OK' if passed else 'FAIL'} "
            f"(FastMCP={has_fastmcp}, main_guard={has_main})"
        )
    report.append("")
    report.append(f"Summary: {ok}/{checked} files passed.")
    report.append("")
    return "\n".join(report).strip() + "\n"


def scenario_generate_changelog(root: Path) -> str:
    """
    Goal-level scenario:
    "Сгенерировать changelog на основе текущего git diff."
    """
    diff_name = _run_cmd(root, ["git", "diff", "--name-only"])
    files = [x.strip() for x in diff_name.splitlines() if x.strip()]
    sections = {
        "API": [f for f in files if f.startswith("api/")],
        "MCP Servers": [f for f in files if f.startswith("mcp_servers/")],
        "RAG / Scripts": [f for f in files if f.startswith("scripts/")],
        "Frontend": [f for f in files if f.startswith("frontend/")],
        "Docs": [f for f in files if f.startswith("docs/")],
        "Other": [f for f in files if f not in set(sum([v for v in [[], []]], []))],
    }

    lines: list[str] = ["# AI Changelog (Generated)", ""]
    lines.append("Этот файл сгенерирован сценарием file-assistant на основе `git diff --name-only`.")
    lines.append("")
    lines.append(f"Total changed files: **{len(files)}**")
    lines.append("")

    used: set[str] = set()
    for title, arr in (
        ("API", sections["API"]),
        ("MCP Servers", sections["MCP Servers"]),
        ("RAG / Scripts", sections["RAG / Scripts"]),
        ("Frontend", sections["Frontend"]),
        ("Docs", sections["Docs"]),
    ):
        if not arr:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for f in arr:
            lines.append(f"- `{f}`")
            used.add(f)
        lines.append("")
    other = [f for f in files if f not in used]
    if other:
        lines.append("## Other")
        lines.append("")
        for f in other:
            lines.append(f"- `{f}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Run goal-based file assistant scenarios.")
    p.add_argument("--output-dir", default="artifacts/file_assistant_scenarios")
    args = p.parse_args()
    root = Path(__file__).resolve().parent.parent
    out_dir = (root / args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    usage_report = scenario_find_api_usages()
    inv_report = scenario_check_file_invariants()
    changelog = scenario_generate_changelog(root)

    _write(str(out_dir / "scenario1_api_usage_report.md"), usage_report)
    _write(str(out_dir / "scenario2_invariants_report.md"), inv_report)
    _write(str(out_dir / "scenario3_changelog.md"), changelog)

    summary = {
        "ok": True,
        "scenarios": [
            "find_api_usages",
            "check_file_invariants",
            "generate_changelog",
        ],
        "outputs": [
            str(out_dir / "scenario1_api_usage_report.md"),
            str(out_dir / "scenario2_invariants_report.md"),
            str(out_dir / "scenario3_changelog.md"),
        ],
    }
    _write(str(out_dir / "summary.json"), json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
