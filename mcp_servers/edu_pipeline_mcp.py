"""
Учебный MCP-сервер (FastMCP): search -> summarize -> saveToFile.

Запуск stdio:
  .venv/bin/python -m mcp_servers.edu_pipeline_mcp stdio

Запуск Streamable HTTP:
  FASTMCP_PORT=3334 .venv/bin/python -m mcp_servers.edu_pipeline_mcp streamable-http
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

YANDEX_WEATHER_BASE = "https://api.weather.yandex.ru/v1/forecast"

mcp = FastMCP(
    "Edu-Pipeline",
    instructions=(
        "Учебные инструменты MCP: поиск данных, суммаризация, сохранение в файл."
    ),
    host="127.0.0.1",
    port=3334,
    streamable_http_path="/mcp",
    json_response=True,
)


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _project_root() -> Path:
    # Файл расположен в /mcp_servers, корень проекта на уровень выше.
    return Path(__file__).resolve().parents[1]


# Для запуска MCP как stdio subprocess переменные из .env
# не всегда попадают в окружение автоматически.
_ROOT = _project_root()
load_dotenv(_ROOT / ".env")
load_dotenv()


@mcp.tool()
def search(query: str, limit: int = 5) -> str:
    """Получает погодные данные из Yandex Weather API.

    Формат query:
      - "город" (поддержаны: Иркутск, Москва, Санкт-Петербург, Новосибирск, Екатеринбург)
      - "lat,lon" (например "52.286974,104.305018")

    Args:
        query: Город или координаты lat,lon.
        limit: Количество дней прогноза (1-7), по умолчанию 5.
    """
    key = os.environ.get("YANDEX_WEATHER_KEY", "").strip()
    if not key:
        raise ValueError("YANDEX_WEATHER_KEY не задан")

    q = (query or "").strip()
    if not q:
        raise ValueError("query не может быть пустым")
    days = max(1, min(7, int(limit)))

    city_coords: dict[str, tuple[float, float]] = {
        "иркутск": (52.2869741, 104.3050183),
        "irkutsk": (52.2869741, 104.3050183),
        "москва": (55.7558, 37.6176),
        "moscow": (55.7558, 37.6176),
        "санкт-петербург": (59.9343, 30.3351),
        "saint petersburg": (59.9343, 30.3351),
        "новосибирск": (55.0084, 82.9357),
        "novosibirsk": (55.0084, 82.9357),
        "екатеринбург": (56.8389, 60.6057),
        "yekaterinburg": (56.8389, 60.6057),
    }

    lat: float
    lon: float
    q_lower = q.lower()
    if "," in q:
        parts = [p.strip() for p in q.split(",", 1)]
        if len(parts) != 2:
            raise ValueError("Координаты ожидаются в формате lat,lon")
        lat = float(parts[0])
        lon = float(parts[1])
    elif q_lower in city_coords:
        lat, lon = city_coords[q_lower]
    else:
        raise ValueError(
            "Неизвестный город. Используйте один из пресетов или формат lat,lon."
        )

    if not -90 <= lat <= 90:
        raise ValueError("latitude должна быть в [-90, 90]")
    if not -180 <= lon <= 180:
        raise ValueError("longitude должна быть в [-180, 180]")

    r = requests.get(
        YANDEX_WEATHER_BASE,
        params={
            "lat": lat,
            "lon": lon,
            "lang": "ru_RU",
            "limit": days,
            "hours": "false",
        },
        headers={"X-Yandex-Weather-Key": key},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Неожиданный формат ответа Yandex Weather API")

    fact = data.get("fact")
    forecast_rows = data.get("forecasts")
    if not isinstance(fact, dict):
        raise RuntimeError("В ответе Yandex нет fact")
    if not isinstance(forecast_rows, list):
        forecast_rows = []

    items: list[dict[str, Any]] = []
    for row in forecast_rows:
        if not isinstance(row, dict):
            continue
        parts = row.get("parts")
        day_short = parts.get("day_short") if isinstance(parts, dict) else None
        items.append(
            {
                "date": row.get("date"),
                "condition": day_short.get("condition") if isinstance(day_short, dict) else None,
                "temp_day": day_short.get("temp") if isinstance(day_short, dict) else None,
            }
        )

    return _json(
        {
            "query": q,
            "items": items,
            "current": {
                "temp": fact.get("temp"),
                "condition": fact.get("condition"),
                "wind_speed": fact.get("wind_speed"),
                "obs_time": fact.get("obs_time"),
            },
            "meta": {
                "source": "api.weather.yandex.ru",
                "count": len(items),
                "limit": days,
                "lat": lat,
                "lon": lon,
            },
        }
    )


@mcp.tool()
def summarize(search_result: str, max_chars: int = 500, max_points: int = 5) -> str:
    """Суммаризует результат search.

    Args:
        search_result: JSON-строка с полем items (выход search).
        max_chars: Максимальная длина итогового summary.
        max_points: Сколько ключевых пунктов включать.
    """
    try:
        payload = json.loads(search_result)
    except json.JSONDecodeError as e:
        raise ValueError("search_result должен быть валидной JSON-строкой") from e

    if not isinstance(payload, dict):
        raise ValueError("search_result должен быть JSON-объектом")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("В search_result ожидается список items")

    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    points: list[str] = []
    if current:
        cur_temp = current.get("temp")
        cur_cond = current.get("condition")
        cur_wind = current.get("wind_speed")
        points.append(
            f"Сейчас: {cur_temp}°C, condition={cur_cond}, ветер={cur_wind} м/с"
        )

    for row in items:
        if not isinstance(row, dict):
            continue
        date = str(row.get("date") or "").strip()
        condition = str(row.get("condition") or "").strip()
        temp_day = row.get("temp_day")
        if date or condition or temp_day is not None:
            points.append(f"{date}: {condition}, днем {temp_day}°C")

    mp = max(1, min(20, int(max_points)))
    selected = points[:mp]
    if selected:
        summary = " | ".join(selected)
    else:
        summary = "Подходящих данных для суммаризации не найдено."

    mc = max(80, min(6000, int(max_chars)))
    if len(summary) > mc:
        summary = summary[: mc - 1] + "…"

    return _json(
        {
            "summary": summary,
            "key_points": selected,
            "stats": {
                "input_items": len(items),
                "used_points": len(selected),
                "max_chars": mc,
            },
        }
    )


@mcp.tool()
def saveToFile(content: str, file_path: str, overwrite: bool = False) -> str:
    """Сохраняет текст в файл внутри директории проекта.

    Args:
        content: Что сохранить.
        file_path: Путь относительно корня проекта (например outputs/result.txt).
        overwrite: Разрешить перезапись существующего файла.
    """
    rel = (file_path or "").strip()
    if not rel:
        raise ValueError("file_path не может быть пустым")
    if Path(rel).is_absolute():
        raise ValueError("Используйте относительный file_path внутри проекта")

    root = _project_root()
    out = (root / rel).resolve()
    if root not in out.parents and out != root:
        raise ValueError("file_path должен быть внутри директории проекта")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        raise ValueError("Файл уже существует. Передайте overwrite=true для перезаписи.")
    out.write_text(content, encoding="utf-8")

    return _json(
        {
            "saved": True,
            "path": str(out),
            "bytes": len(content.encode("utf-8")),
        }
    )


def main() -> None:
    import sys

    transport = (sys.argv[1] if len(sys.argv) > 1 else "stdio").strip().lower()
    if transport in ("http", "streamable-http", "streamable_http"):
        transport = "streamable-http"
    elif transport not in ("stdio", "sse"):
        raise SystemExit(
            "Использование: python -m mcp_servers.edu_pipeline_mcp [stdio|streamable-http]"
        )
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
