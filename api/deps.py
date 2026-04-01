from __future__ import annotations

from collections.abc import Iterator
from threading import Lock

from app_settings import SETTINGS
from sqlite_chat_storage import SQLiteChatStorage

_schema_ready = False
_schema_lock = Lock()


def _ensure_schema_once() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        storage = SQLiteChatStorage(db_path=SETTINGS.default_db_path)
        try:
            storage.ensure_schema()
            _schema_ready = True
        finally:
            storage.close()


def get_storage() -> Iterator[SQLiteChatStorage]:
    _ensure_schema_once()
    storage = SQLiteChatStorage(db_path=SETTINGS.default_db_path)
    try:
        yield storage
    finally:
        storage.close()
