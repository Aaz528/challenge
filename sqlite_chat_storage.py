from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChatInfo:
    chat_id: int
    title: str
    total_tokens: int


@dataclass(frozen=True)
class MessageRow:
    message_id: int
    role: str
    content: str
    is_summarized: int


class SQLiteChatStorage:
    def __init__(self, db_path: str = "chats.db") -> None:
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                source_key TEXT UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                is_summarized INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                summary_text TEXT NOT NULL,
                from_message_id INTEGER NOT NULL,
                to_message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute("PRAGMA table_info(messages)")
        cols = [str(r[1]) for r in cur.fetchall()]
        if "is_summarized" not in cols:
            cur.execute("ALTER TABLE messages ADD COLUMN is_summarized INTEGER NOT NULL DEFAULT 0")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id, id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_summary ON messages(chat_id, is_summarized, id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_summaries_chat_id ON summaries(chat_id, id)")
        self._conn.commit()

    def list_chats(self, limit: int = 30) -> list[ChatInfo]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, title, total_tokens
            FROM chats
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [ChatInfo(chat_id=int(r["id"]), title=str(r["title"]), total_tokens=int(r["total_tokens"])) for r in rows]

    def get_chat(self, chat_id: int) -> ChatInfo | None:
        cur = self._conn.cursor()
        cur.execute("SELECT id, title, total_tokens FROM chats WHERE id=?", (chat_id,))
        row = cur.fetchone()
        if not row:
            return None
        return ChatInfo(chat_id=int(row["id"]), title=str(row["title"]), total_tokens=int(row["total_tokens"]))

    def create_chat(
        self,
        *,
        title: str,
        system_prompt: str,
        source_key: str | None = None,
        initial_total_tokens: int = 0,
    ) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO chats (title, system_prompt, total_tokens, source_key)
            VALUES (?, ?, ?, ?)
            """,
            (title, system_prompt, initial_total_tokens, source_key),
        )
        chat_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO messages (chat_id, role, content)
            VALUES (?, ?, ?)
            """,
            (chat_id, "system", system_prompt),
        )
        self._conn.commit()
        return chat_id

    def get_or_create_chat_from_source(
        self,
        *,
        source_key: str,
        title: str,
        system_prompt: str,
        messages: list[dict[str, str]],
        total_tokens: int = 0,
    ) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT id FROM chats WHERE source_key=?", (source_key,))
        row = cur.fetchone()
        if row:
            return int(row["id"])

        cur.execute(
            """
            INSERT INTO chats (title, system_prompt, total_tokens, source_key)
            VALUES (?, ?, ?, ?)
            """,
            (title, system_prompt, total_tokens, source_key),
        )
        chat_id = int(cur.lastrowid)
        if messages:
            values = [(chat_id, str(m.get("role", "")), str(m.get("content", ""))) for m in messages]
            cur.executemany(
                """
                INSERT INTO messages (chat_id, role, content)
                VALUES (?, ?, ?)
                """,
                values,
            )
        self._conn.commit()
        return chat_id

    def get_messages(self, chat_id: int) -> list[dict[str, str]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT role, content
            FROM messages
            WHERE chat_id=?
            ORDER BY id ASC
            """,
            (chat_id,),
        )
        rows = cur.fetchall()
        return [{"role": str(r["role"]), "content": str(r["content"])} for r in rows]

    def get_context_messages(self, chat_id: int) -> list[dict[str, str]]:
        """
        Сообщения для продолжения диалога:
        system + summary-блоки + несуммаризированные user/assistant.
        """
        cur = self._conn.cursor()

        cur.execute(
            """
            SELECT role, content
            FROM messages
            WHERE chat_id=? AND role='system'
            ORDER BY id ASC
            LIMIT 1
            """,
            (chat_id,),
        )
        system_row = cur.fetchone()
        context: list[dict[str, str]] = []
        if system_row:
            context.append({"role": str(system_row["role"]), "content": str(system_row["content"])})

        cur.execute(
            """
            SELECT summary_text
            FROM summaries
            WHERE chat_id=?
            ORDER BY id ASC
            """,
            (chat_id,),
        )
        for r in cur.fetchall():
            context.append(
                {
                    "role": "system",
                    "content": "Сводка предыдущего диалога (архив):\n" + str(r["summary_text"]),
                }
            )

        cur.execute(
            """
            SELECT role, content
            FROM messages
            WHERE chat_id=? AND role IN ('user', 'assistant') AND is_summarized=0
            ORDER BY id ASC
            """,
            (chat_id,),
        )
        for r in cur.fetchall():
            context.append({"role": str(r["role"]), "content": str(r["content"])})

        return context

    def get_unsummarized_message_rows(self, chat_id: int) -> list[MessageRow]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, role, content, is_summarized
            FROM messages
            WHERE chat_id=? AND role IN ('user', 'assistant')
            ORDER BY id ASC
            """,
            (chat_id,),
        )
        rows = cur.fetchall()
        return [
            MessageRow(
                message_id=int(r["id"]),
                role=str(r["role"]),
                content=str(r["content"]),
                is_summarized=int(r["is_summarized"]),
            )
            for r in rows
        ]

    def create_summary_and_mark(
        self,
        *,
        chat_id: int,
        summary_text: str,
        from_message_id: int,
        to_message_id: int,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO summaries (chat_id, summary_text, from_message_id, to_message_id)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, summary_text, from_message_id, to_message_id),
        )
        cur.execute(
            """
            UPDATE messages
            SET is_summarized=1
            WHERE chat_id=? AND id>=? AND id<=? AND role IN ('user', 'assistant')
            """,
            (chat_id, from_message_id, to_message_id),
        )
        cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
        self._conn.commit()

    def append_message(self, chat_id: int, role: str, content: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO messages (chat_id, role, content)
            VALUES (?, ?, ?)
            """,
            (chat_id, role, content),
        )
        cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
        self._conn.commit()

    def add_tokens(self, chat_id: int, delta_tokens: int) -> None:
        if delta_tokens <= 0:
            return
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE chats
            SET total_tokens = total_tokens + ?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (delta_tokens, chat_id),
        )
        self._conn.commit()

