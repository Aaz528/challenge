"""
Open-Meteo MCP (FastMCP): погода и геокодинг без API-ключа.

Запуск stdio (для Cursor / вашего mcp_client по MCP_TRANSPORT=stdio):
  .venv/bin/python -m mcp_servers.open_meteo_mcp stdio

Запуск Streamable HTTP на 127.0.0.1:3333 (в .env основного API: MCP_STREAMABLE_HTTP_URL=http://127.0.0.1:3333/mcp):
  FASTMCP_PORT=3333 .venv/bin/python -m mcp_servers.open_meteo_mcp streamable-http

Документация API: https://open-meteo.com/en/docs
"""

from __future__ import annotations

import json
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
GEOCODING_BASE = "https://geocoding-api.open-meteo.com/v1/search"

mcp = FastMCP(
    "Open-Meteo",
    instructions=(
        "Инструменты для бесплатного API Open-Meteo: прогноз по широте/долготе и поиск координат по названию места."
    ),
    host="127.0.0.1",
    port=3333,
    streamable_http_path="/mcp",
    json_response=True,
)


def _get_json(url: str, params: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Неожиданный формат ответа API")
    return data


@mcp.tool()
def weather_forecast(
    latitude: float,
    longitude: float,
    forecast_days: int = 3,
) -> str:
    """Текущая погода и почасовой прогноз по координатам (Open-Meteo).

    Args:
        latitude: Широта, градусы (например 55.75 для Москвы).
        longitude: Долгота, градусы (например 37.62).
        forecast_days: Сколько дней прогноза (1–16), по умолчанию 3.
    """
    if not -90 <= latitude <= 90:
        raise ValueError("latitude должна быть в [-90, 90]")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude должна быть в [-180, 180]")
    fd = max(1, min(16, int(forecast_days)))

    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_days": fd,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "weather_code,wind_speed_10m"
        ),
        "hourly": "temperature_2m,precipitation_probability",
        "timezone": "auto",
    }
    data = _get_json(FORECAST_BASE, params)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def search_location(query: str, count: int = 5) -> str:
    """Поиск места по названию; возвращает координаты и регион (геокодинг Open-Meteo).

    Args:
        query: Название города или региона (например «Москва», «Berlin»).
        count: Максимум результатов (1–20), по умолчанию 5.
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query не может быть пустым")
    n = max(1, min(20, int(count)))
    data = _get_json(
        GEOCODING_BASE,
        {"name": q, "count": n, "language": "ru", "format": "json"},
    )
    return json.dumps(data, ensure_ascii=False, indent=2)


def main() -> None:
    import sys

    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        transport = "streamable-http"
    elif transport not in ("stdio", "sse"):
        raise SystemExit(
            "Использование: python -m mcp_servers.open_meteo_mcp [stdio|streamable-http]"
        )
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
