"""
Yandex Geocoder MCP (FastMCP): прямой и обратный геокодинг.

Требуется в .env: YANDEX_GEOCODER_API_KEY

Запуск stdio:
  .venv/bin/python -m mcp_servers.yandex_geocoder_mcp stdio

Документация: https://yandex.ru/dev/maps/geocoder/
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

GEOCODER_BASE = "https://geocode-maps.yandex.ru/1.x/"

mcp = FastMCP(
    "Yandex-Geocoder",
    instructions="Геокодирование адреса в координаты и обратное геокодирование (Яндекс Карты API).",
    host="127.0.0.1",
    port=3336,
    streamable_http_path="/mcp",
    json_response=True,
)


def _api_key() -> str:
    key = os.environ.get("YANDEX_GEOCODER_API_KEY", "").strip()
    if not key:
        raise ValueError("YANDEX_GEOCODER_API_KEY не задан")
    return key


def _geocode_request(*, geocode: str, results: int = 5) -> dict[str, Any]:
    r = requests.get(
        GEOCODER_BASE,
        params={
            "apikey": _api_key(),
            "geocode": geocode,
            "format": "json",
            "results": max(1, min(10, int(results))),
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Неожиданный ответ геокодера")
    return data


def _json_str(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool()
def geocode_address(address: str, results: int = 5) -> str:
    """Адрес или название места → координаты и метаданные GeoObjects.

    Args:
        address: Строка запроса (например «Иркутск, Ленина 1»).
        results: Сколько результатов (1–10).
    """
    s = (address or "").strip()
    if not s:
        raise ValueError("address не может быть пустым")
    return _json_str(_geocode_request(geocode=s, results=results))


@mcp.tool()
def reverse_geocode(longitude: float, latitude: float, results: int = 5) -> str:
    """Координаты → адрес (долгота, широта в формате API Яндекса).

    Args:
        longitude: Долгота, градусы.
        latitude: Широта, градусы.
        results: Сколько результатов (1–10).
    """
    if not -180 <= longitude <= 180:
        raise ValueError("longitude вне [-180, 180]")
    if not -90 <= latitude <= 90:
        raise ValueError("latitude вне [-90, 90]")
    # Яндекс: geocode=долгота,широта
    geocode = f"{longitude},{latitude}"
    return _json_str(_geocode_request(geocode=geocode, results=results))


def main() -> None:
    import sys

    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        transport = "streamable-http"
    elif transport not in ("stdio", "sse"):
        raise SystemExit(
            "Использование: python -m mcp_servers.yandex_geocoder_mcp [stdio|streamable-http]"
        )
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
