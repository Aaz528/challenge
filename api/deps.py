from __future__ import annotations

from app_settings import SETTINGS
from chat_service import migrate_toon_chats
from sqlite_chat_storage import SQLiteChatStorage

_storage: SQLiteChatStorage | None = None


def get_storage() -> SQLiteChatStorage:
    global _storage
    if _storage is None:
        _storage = SQLiteChatStorage(db_path=SETTINGS.default_db_path)
        _storage.ensure_schema()
        migrate_toon_chats(_storage, SETTINGS.default_system_prompt)
    return _storage
