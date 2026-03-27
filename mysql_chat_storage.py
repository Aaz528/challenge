from __future__ import annotations

import os
from dataclasses import dataclass

import pymysql
from dotenv import load_dotenv


@dataclass(frozen=True)
class ChatInfo:
    chat_id: int
    title: str
    total_tokens: int


class MySQLChatStorage:
    def __init__(self) -> None:
        load_dotenv()
        self._conn = pymysql.connect(
            host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DATABASE", "llm_agent"),
            charset="utf8mb4",
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def close(self) -> None:
        self._conn.close()

    def ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    title VARCHAR(255) NOT NULL,
                    system_prompt TEXT NOT NULL,
                    total_tokens BIGINT NOT NULL DEFAULT 0,
                    source_key VARCHAR(255) NULL UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    chat_id BIGINT NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    content LONGTEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
                    INDEX idx_messages_chat_id (chat_id, id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

    def list_chats(self, limit: int = 30) -> list[ChatInfo]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, total_tokens
                FROM chats
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [ChatInfo(chat_id=int(r["id"]), title=str(r["title"]), total_tokens=int(r["total_tokens"])) for r in rows]

    def get_chat(self, chat_id: int) -> ChatInfo | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT id, title, total_tokens FROM chats WHERE id=%s", (chat_id,))
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
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chats (title, system_prompt, total_tokens, source_key)
                VALUES (%s, %s, %s, %s)
                """,
                (title, system_prompt, initial_total_tokens, source_key),
            )
            chat_id = int(cur.lastrowid)
            cur.execute(
                """
                INSERT INTO messages (chat_id, role, content)
                VALUES (%s, %s, %s)
                """,
                (chat_id, "system", system_prompt),
            )
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
        with self._conn.cursor() as cur:
            cur.execute("SELECT id FROM chats WHERE source_key=%s", (source_key,))
            row = cur.fetchone()
            if row:
                return int(row["id"])

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chats (title, system_prompt, total_tokens, source_key)
                VALUES (%s, %s, %s, %s)
                """,
                (title, system_prompt, total_tokens, source_key),
            )
            chat_id = int(cur.lastrowid)
            if messages:
                values = [(chat_id, str(m.get("role", "")), str(m.get("content", ""))) for m in messages]
                cur.executemany(
                    """
                    INSERT INTO messages (chat_id, role, content)
                    VALUES (%s, %s, %s)
                    """,
                    values,
                )
            return chat_id

    def get_messages(self, chat_id: int) -> list[dict[str, str]]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM messages
                WHERE chat_id=%s
                ORDER BY id ASC
                """,
                (chat_id,),
            )
            rows = cur.fetchall()
        return [{"role": str(r["role"]), "content": str(r["content"])} for r in rows]

    def append_message(self, chat_id: int, role: str, content: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (chat_id, role, content)
                VALUES (%s, %s, %s)
                """,
                (chat_id, role, content),
            )

    def add_tokens(self, chat_id: int, delta_tokens: int) -> None:
        if delta_tokens <= 0:
            return
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chats
                SET total_tokens = total_tokens + %s
                WHERE id=%s
                """,
                (delta_tokens, chat_id),
            )

