from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SummarySettings:
    # Минимум завершенных ходов (user+assistant), чтобы запускать сворачивание.
    min_turns_to_rollup: int = 6
    # Сколько последних ходов всегда оставляем "живыми" (без сворачивания).
    keep_last_turns: int = 2
    # Сколько ходов сворачиваем за одну итерацию.
    rollup_turns_per_batch: int = 4


@dataclass(frozen=True)
class CLISettings:
    default_system_prompt: str = "Отвечай по существу запроса пользователя."
    default_timeout_sec: float = 60.0
    default_temperature: float = 0.3
    default_max_tokens: int = 1024
    default_db_path: str = "chats.db"
    chat_list_limit: int = 20
    exit_commands: tuple[str, ...] = ("exit", "quit", "q", "/exit")


SETTINGS = CLISettings()
SUMMARY_SETTINGS = SummarySettings()


@dataclass(frozen=True)
class WebSettings:
    """HTTP API (FastAPI)."""
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    )


WEB_SETTINGS = WebSettings()


@dataclass(frozen=True)
class MCPSettings:
    """Подключение MCP-клиента (официальный SDK). Переменные MCP_* — см. load_mcp_settings()."""

    enabled: bool = False
    # stdio | streamable_http
    transport: str = ""
    stdio_command: str = ""
    stdio_args: tuple[str, ...] = ()
    streamable_http_url: str = ""
    # Таймаут HTTP для streamable_http (сек). SDK иначе даёт read до 300s — «висит» при неверном URL.
    http_timeout_sec: float = 45.0
    # Заголовки для удалённого MCP (Authorization и т.д.): MCP_STREAMABLE_HTTP_HEADERS_JSON
    streamable_http_headers: tuple[tuple[str, str], ...] = ()


MCP_DEFAULTS = MCPSettings()


def _parse_mcp_stdio_args(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(
            'MCP_STDIO_ARGS должен быть JSON-массивом строк, например ["-y","@scope/pkg"]'
        )
    return [str(x) for x in data]


def _parse_mcp_http_headers_json(raw: str) -> tuple[tuple[str, str], ...]:
    raw = (raw or "").strip()
    if not raw:
        return ()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("MCP_STREAMABLE_HTTP_HEADERS_JSON должен быть JSON-объектом {\"Header-Name\": \"value\"}")
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        out.append((str(k), str(v)))
    return tuple(out)


def load_mcp_settings() -> MCPSettings:
    """Читает MCP_* из окружения. Не импортирует пакет mcp — безопасно для лёгких эндпоинтов вроде /api/mcp/config."""
    enabled = os.environ.get("MCP_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
    transport = os.environ.get("MCP_TRANSPORT", "").strip().lower()
    cmd = os.environ.get("MCP_STDIO_COMMAND", "").strip()
    args_raw = os.environ.get("MCP_STDIO_ARGS", "").strip()
    url = os.environ.get("MCP_STREAMABLE_HTTP_URL", "").strip()
    args = _parse_mcp_stdio_args(args_raw)
    try:
        http_timeout_sec = float(os.environ.get("MCP_HTTP_TIMEOUT_SEC", "45").strip() or "45")
    except ValueError:
        http_timeout_sec = 45.0
    headers_raw = os.environ.get("MCP_STREAMABLE_HTTP_HEADERS_JSON", "").strip()
    try:
        streamable_http_headers = _parse_mcp_http_headers_json(headers_raw)
    except (json.JSONDecodeError, ValueError):
        streamable_http_headers = ()
    return MCPSettings(
        enabled=enabled,
        transport=transport,
        stdio_command=cmd,
        stdio_args=tuple(args),
        streamable_http_url=url,
        http_timeout_sec=http_timeout_sec,
        streamable_http_headers=streamable_http_headers,
    )


# Стратегии памяти ветки (см. chat_service / sqlite_chat_storage)
MEMORY_STRATEGY_DEFAULT = "default"
MEMORY_STRATEGY_SUMMARY = "summary"
MEMORY_STRATEGY_SLIDING = "sliding_window"
MEMORY_STRATEGY_STICKY = "sticky_facts"
MEMORY_STRATEGY_TRIPLE = "triple_memory"
MEMORY_STRATEGIES = (
    MEMORY_STRATEGY_DEFAULT,
    MEMORY_STRATEGY_SUMMARY,
    MEMORY_STRATEGY_SLIDING,
    MEMORY_STRATEGY_STICKY,
    MEMORY_STRATEGY_TRIPLE,
)


@dataclass(frozen=True)
class MemoryStrategyDefaults:
    """Параметры по умолчанию для strategy_params_json (переопределяются в ветке)."""
    # sliding_window: сколько последних сообщений user+assistant держать в БД и в промпте
    sliding_window_messages: int = 20
    # sticky_facts: сколько последних сообщений user+assistant добавлять к facts в промпт
    sticky_tail_messages: int = 12
    # triple_memory: сколько последних user+assistant сообщений брать в short-term блок.
    triple_short_tail_messages: int = 12
    # triple_memory: fallback user_id для long-term памяти, если не задан в strategy_params_json.
    triple_default_user_id: str = "profile_starter"


MEMORY_DEFAULTS = MemoryStrategyDefaults()


# Инварианты (хранятся отдельно от диалога, scope: user_id)
INVARIANT_CATEGORIES = (
    "architecture",
    "decision",
    "stack",
    "business",
    "other",
)
INVARIANT_SEVERITIES = ("hard", "soft")


MEMORY_PROFILE_PRESETS = (
    {
        "id": "profile_basic",
        "title": "Базовый",
        "description": "Базовый универсальный профиль общения и предпочтений.",
        "entries": {
            "name": "User",
            "language": "ru",
            "answer_style": "кратко и структурированно",
            "role": "software engineer",
            "main_stack": "python, fastapi, react",
            "project_context": "локальный AI-ассистент с ветками и памятью",
            "priorities": "надежность, поддерживаемость, ясность",
            "constraints": "без усложнения инфраструктуры",
            "testing_preferences": "smoke + сборка + базовые проверки",
            "delivery_format": "короткий итог + детали + next steps",
        },
    },
    {
        "id": "profile_starter",
        "title": "Стартовый",
        "description": "Стартовый профиль для быстрого начала работы.",
        "entries": {
            "name": "Nout",
            "language": "ru",
            "answer_style": "кратко, по делу, с конкретными шагами",
            "role": "fullstack developer",
            "main_stack": "python, fastapi, react, sqlite",
            "project_context": "локальный AI-ассистент с ветками чатов и многоуровневой памятью",
            "priorities": "надежность и простота поддержки",
            "constraints": "минимум сложной инфраструктуры, локальный запуск",
            "testing_preferences": "быстрые smoke + сборка фронта + py_compile",
            "delivery_format": "сначала итог, потом детали и что проверить",
        },
    },
)

