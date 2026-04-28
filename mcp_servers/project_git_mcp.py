"""
MCP-сервер для доступа к текущему git-проекту.

Минимальный инструмент:
- currentBranch: вернуть текущую git-ветку

Опциональные инструменты:
- listProjectFiles: список файлов проекта (по умолчанию git ls-files)
- gitDiff: diff рабочего дерева (или заданного сравнения)

Запуск stdio:
  .venv/bin/python -m mcp_servers.project_git_mcp stdio

Запуск Streamable HTTP:
  FASTMCP_PORT=3340 .venv/bin/python -m mcp_servers.project_git_mcp streamable-http
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Project-Git",
    instructions="Инструменты MCP для чтения состояния git-репозитория текущего проекта.",
    host="127.0.0.1",
    port=3340,
    streamable_http_path="/mcp",
    json_response=True,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _run_git(args: list[str], *, timeout_sec: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(_project_root()),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


@mcp.tool()
def currentBranch() -> str:
    """Возвращает имя текущей git-ветки проекта."""
    p = _run_git(["branch", "--show-current"])
    branch = (p.stdout or "").strip()
    if p.returncode != 0:
        return _json(
            {
                "ok": False,
                "error": (p.stderr or p.stdout or "").strip() or "git branch failed",
            }
        )
    return _json(
        {
            "ok": True,
            "branch": branch,
            "repo_root": str(_project_root()),
        }
    )


@mcp.tool()
def listProjectFiles(limit: int = 200, include_untracked: bool = False) -> str:
    """Возвращает список файлов проекта.

    По умолчанию используются tracked файлы (`git ls-files`).
    При include_untracked=true добавляются untracked (`git ls-files --others --exclude-standard`).
    """
    lim = max(1, min(5000, int(limit)))
    tracked = _run_git(["ls-files"])
    if tracked.returncode != 0:
        return _json(
            {
                "ok": False,
                "error": (tracked.stderr or tracked.stdout or "").strip() or "git ls-files failed",
            }
        )

    files = [ln.strip() for ln in (tracked.stdout or "").splitlines() if ln.strip()]
    if include_untracked:
        untracked = _run_git(["ls-files", "--others", "--exclude-standard"])
        if untracked.returncode == 0:
            files.extend([ln.strip() for ln in (untracked.stdout or "").splitlines() if ln.strip()])
    uniq = sorted(dict.fromkeys(files))
    return _json(
        {
            "ok": True,
            "count": len(uniq),
            "limit": lim,
            "files": uniq[:lim],
        }
    )


@mcp.tool()
def gitDiff(
    ref: str = "",
    staged: bool = False,
    file_path: str = "",
    max_chars: int = 12000,
) -> str:
    """Возвращает git diff.

    Args:
      ref: Опциональная ссылка сравнения, например "HEAD~1".
      staged: Если true — diff staged изменений.
      file_path: Опциональный относительный путь для ограничения diff.
      max_chars: Ограничение длины вывода diff.
    """
    mc = max(200, min(100000, int(max_chars)))
    args: list[str] = ["diff"]
    if staged:
        args.append("--cached")
    if ref.strip():
        args.append(ref.strip())
    if file_path.strip():
        args.extend(["--", file_path.strip()])
    p = _run_git(args, timeout_sec=45)
    if p.returncode != 0:
        return _json(
            {
                "ok": False,
                "error": (p.stderr or p.stdout or "").strip() or "git diff failed",
                "args": args,
            }
        )
    diff_text = p.stdout or ""
    truncated = False
    if len(diff_text) > mc:
        diff_text = diff_text[: mc - 1] + "…"
        truncated = True
    return _json(
        {
            "ok": True,
            "args": args,
            "truncated": truncated,
            "diff": diff_text,
        }
    )


def main() -> None:
    import sys

    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        transport = "streamable-http"
    elif transport not in ("stdio", "sse"):
        raise SystemExit("Использование: python -m mcp_servers.project_git_mcp [stdio|streamable-http]")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
