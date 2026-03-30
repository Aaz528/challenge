from __future__ import annotations

from app_settings import SETTINGS
from sqlite_chat_storage import SQLiteChatStorage

_storage: SQLiteChatStorage | None = None


def get_storage() -> SQLiteChatStorage:
    global _storage
    if _storage is None:
        _storage = SQLiteChatStorage(db_path=SETTINGS.default_db_path)
        _storage.ensure_schema()
    return _storage
