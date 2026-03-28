from __future__ import annotations

from dataclasses import dataclass, field


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
    # Переопределяем заголовки для уже известных импортов.
    fixed_import_titles: dict[str, str] = field(
        default_factory=lambda: {
            "chat.toon": "Исторический подкаст о Руси",
            "chat2.toon": "Аналоги Starlink",
        }
    )


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
    )


WEB_SETTINGS = WebSettings()


# Стратегии памяти ветки (см. chat_service / sqlite_chat_storage)
MEMORY_STRATEGY_DEFAULT = "default"
MEMORY_STRATEGY_SUMMARY = "summary"
MEMORY_STRATEGY_SLIDING = "sliding_window"
MEMORY_STRATEGY_STICKY = "sticky_facts"
MEMORY_STRATEGIES = (
    MEMORY_STRATEGY_DEFAULT,
    MEMORY_STRATEGY_SUMMARY,
    MEMORY_STRATEGY_SLIDING,
    MEMORY_STRATEGY_STICKY,
)


@dataclass(frozen=True)
class MemoryStrategyDefaults:
    """Параметры по умолчанию для strategy_params_json (переопределяются в ветке)."""
    # sliding_window: сколько последних сообщений user+assistant держать в БД и в промпте
    sliding_window_messages: int = 20
    # sticky_facts: сколько последних сообщений user+assistant добавлять к facts в промпт
    sticky_tail_messages: int = 12


MEMORY_DEFAULTS = MemoryStrategyDefaults()

