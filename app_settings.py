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

