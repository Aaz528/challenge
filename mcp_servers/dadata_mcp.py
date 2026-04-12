"""
DaData MCP (FastMCP): подсказки адресов и стандартизация (РФ).

Требуется в .env: DADATA_TOKEN, DADATA_SECRET (для clean).

Запуск stdio:
  .venv/bin/python -m mcp_servers.dadata_mcp stdio

Документация: https://dadata.ru/api/suggest/address/ , https://dadata.ru/api/clean/address/
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
load_dotenv()

SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"
CLEAN_URL = "https://cleaner.dadata.ru/api/v1/clean/address"

mcp = FastMCP(
    "DaData",
    instructions="Подсказки адресов и очистка адреса через DaData API (Россия).",
    host="127.0.0.1",
    port=3335,
    streamable_http_path="/mcp",
    json_response=True,
)


def _token_headers() -> dict[str, str]:
    token = os.environ.get("DADATA_TOKEN", "").strip()
    if not token:
        raise ValueError("DADATA_TOKEN не задан")
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _clean_headers() -> dict[str, str]:
    h = _token_headers()
    secret = os.environ.get("DADATA_SECRET", "").strip()
    if not secret:
        raise ValueError("DADATA_SECRET не задан (нужен для clean/address)")
    h["X-Secret"] = secret
    return h


def _json_str(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool()
def address_suggest(query: str, count: int = 7) -> str:
    """Подсказки адреса по частичному вводу (suggest/address).

    Args:
        query: Строка поиска (например «москва тверская»).
        count: Число подсказок (1–20).
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query не может быть пустым")
    n = max(1, min(20, int(count)))
    r = requests.post(
        SUGGEST_URL,
        headers=_token_headers(),
        json={"query": q, "count": n},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Неожиданный ответ DaData")
    return _json_str(data)


@mcp.tool()
def clean_address(address: str) -> str:
    """Стандартизация одного адресного поля (clean/address).

    Args:
        address: Полный адрес одной строкой.
    """
    s = (address or "").strip()
    if not s:
        raise ValueError("address не может быть пустым")
    r = requests.post(
        CLEAN_URL,
        headers=_clean_headers(),
        json=[s],
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Неожиданный ответ DaData")
    return _json_str(data)


def main() -> None:
    import sys

    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        transport = "streamable-http"
    elif transport not in ("stdio", "sse"):
        raise SystemExit(
            "Использование: python -m mcp_servers.dadata_mcp [stdio|streamable-http]"
        )
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
