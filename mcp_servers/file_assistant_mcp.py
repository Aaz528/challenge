"""
MCP-сервер для работы с файлами проекта (read/search/analyze/write/edit).

Инструменты:
- readProjectFile
- searchProject
- analyzeFiles
- writeProjectFile
- replaceInProjectFile

Запуск stdio:
  .venv/bin/python -m mcp_servers.file_assistant_mcp stdio
"""

from __future__ import annotations

import json
import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "File-Assistant",
    instructions="Инструменты для чтения, поиска, анализа и изменения файлов проекта.",
    host="127.0.0.1",
    port=3343,
    streamable_http_path="/mcp",
    json_response=True,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _safe_project_path(rel_path: str) -> Path:
    rel = (rel_path or "").strip()
    if not rel:
        raise ValueError("path не может быть пустым")
    p = Path(rel)
    if p.is_absolute():
        raise ValueError("Используйте относительный путь внутри проекта")
    root = _project_root()
    out = (root / p).resolve()
    if root not in out.parents and out != root:
        raise ValueError("path должен быть внутри директории проекта")
    return out


@mcp.tool()
def readProjectFile(path: str, start_line: int = 1, max_lines: int = 200) -> str:
    """Читает файл проекта c диапазоном строк."""
    fp = _safe_project_path(path)
    if not fp.exists() or not fp.is_file():
        return _json({"ok": False, "error": f"file not found: {path}"})
    lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
    total = len(lines)
    sl = max(1, int(start_line))
    ml = max(1, min(2000, int(max_lines)))
    a = sl - 1
    b = min(total, a + ml)
    chunk = lines[a:b]
    content = "\n".join(f"{i+1}|{line}" for i, line in enumerate(chunk, start=a))
    return _json(
        {
            "ok": True,
            "path": str(fp),
            "start_line": sl,
            "end_line": b,
            "total_lines": total,
            "content": content,
        }
    )


@mcp.tool()
def searchProject(pattern: str, glob: str = "", max_results: int = 80) -> str:
    """Ищет regex-паттерн по файлам проекта через rg."""
    pat = (pattern or "").strip()
    if not pat:
        return _json({"ok": False, "error": "pattern не может быть пустым"})
    mr = max(1, min(500, int(max_results)))
    cmd = ["rg", "-n", "-S", "--max-count", str(mr), pat]
    if glob.strip():
        cmd.extend(["--glob", glob.strip()])
    try:
        p = subprocess.run(
            cmd,
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if p.returncode not in (0, 1):
            return _json({"ok": False, "error": (p.stderr or p.stdout or "").strip()})
        out = p.stdout.strip()
        items = out.splitlines() if out else []
        return _json({"ok": True, "count": len(items), "matches": items, "engine": "rg"})
    except FileNotFoundError:
        # Fallback если rg не установлен в окружении.
        rx = re.compile(pat)
        root = _project_root()
        g = glob.strip() or "*"
        matches: list[str] = []
        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            base = Path(dirpath)
            for name in filenames:
                fp = base / name
                rel = fp.relative_to(root).as_posix()
                if g and not fnmatch.fnmatch(rel, g):
                    continue
                try:
                    lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    continue
                for i, line in enumerate(lines, start=1):
                    if rx.search(line):
                        matches.append(f"{rel}:{i}:{line}")
                        if len(matches) >= mr:
                            return _json(
                                {
                                    "ok": True,
                                    "count": len(matches),
                                    "matches": matches,
                                    "engine": "python-fallback",
                                }
                            )
        return _json({"ok": True, "count": len(matches), "matches": matches, "engine": "python-fallback"})


@mcp.tool()
def analyzeFiles(file_paths: list[str], question: str = "") -> str:
    """Быстрый анализ нескольких файлов: размеры, строки, ключевые сигнатуры."""
    if not isinstance(file_paths, list) or len(file_paths) == 0:
        return _json({"ok": False, "error": "file_paths должен быть непустым массивом строк"})
    q = (question or "").strip()
    summary: list[dict[str, Any]] = []
    for item in file_paths[:40]:
        p = _safe_project_path(str(item))
        if not p.exists() or not p.is_file():
            summary.append({"path": str(item), "exists": False})
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        sig = [ln.strip() for ln in lines if re.match(r"^\s*(def|class|async def|function)\s+", ln.strip())][:12]
        hit = []
        if q:
            q_words = [w.lower() for w in re.findall(r"[a-zA-Zа-яА-Я0-9_]{4,}", q)]
            low = text.lower()
            hit = [w for w in q_words if w in low][:20]
        summary.append(
            {
                "path": str(p),
                "exists": True,
                "chars": len(text),
                "lines": len(lines),
                "signatures": sig,
                "question_hits": hit,
            }
        )
    return _json({"ok": True, "question": q, "files": summary})


@mcp.tool()
def writeProjectFile(path: str, content: str, overwrite: bool = False) -> str:
    """Создаёт/перезаписывает файл внутри проекта."""
    fp = _safe_project_path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    if fp.exists() and not overwrite:
        return _json({"ok": False, "error": "Файл уже существует; используйте overwrite=true"})
    fp.write_text(content, encoding="utf-8")
    return _json({"ok": True, "path": str(fp), "bytes": len(content.encode('utf-8'))})


@mcp.tool()
def replaceInProjectFile(path: str, find_text: str, replace_text: str, replace_all: bool = False) -> str:
    """Заменяет текст в файле (первое вхождение или все)."""
    fp = _safe_project_path(path)
    if not fp.exists() or not fp.is_file():
        return _json({"ok": False, "error": f"file not found: {path}"})
    old = fp.read_text(encoding="utf-8", errors="ignore")
    needle = str(find_text)
    if not needle:
        return _json({"ok": False, "error": "find_text не может быть пустым"})
    if needle not in old:
        return _json({"ok": False, "error": "find_text не найден в файле"})
    if replace_all:
        new = old.replace(needle, str(replace_text))
    else:
        new = old.replace(needle, str(replace_text), 1)
    fp.write_text(new, encoding="utf-8")
    return _json(
        {
            "ok": True,
            "path": str(fp),
            "changed_bytes": abs(len(new.encode("utf-8")) - len(old.encode("utf-8"))),
            "replace_all": bool(replace_all),
        }
    )


def main() -> None:
    import sys

    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        transport = "streamable-http"
    elif transport not in ("stdio", "sse"):
        raise SystemExit("Использование: python -m mcp_servers.file_assistant_mcp [stdio|streamable-http]")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
