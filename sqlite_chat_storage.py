from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app_settings import MEMORY_STRATEGY_SUMMARY, SETTINGS


@dataclass(frozen=True)
class ChatInfo:
    chat_id: int
    title: str
    total_tokens: int


@dataclass(frozen=True)
class BranchInfo:
    branch_id: int
    chat_id: int
    parent_branch_id: int | None
    fork_after_message_id: int | None
    title: str
    system_prompt: str
    temperature: float
    max_tokens: int
    timeout_sec: float
    total_tokens: int
    memory_strategy: str
    strategy_params_json: str


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
        self._conn.execute("PRAGMA foreign_keys = ON")

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
            CREATE TABLE IF NOT EXISTS branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                parent_branch_id INTEGER,
                fork_after_message_id INTEGER,
                title TEXT NOT NULL DEFAULT 'Основная',
                system_prompt TEXT NOT NULL,
                temperature REAL NOT NULL,
                max_tokens INTEGER NOT NULL,
                timeout_sec REAL NOT NULL,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_branch_id) REFERENCES branches(id) ON DELETE SET NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                branch_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                is_summarized INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                branch_id INTEGER,
                summary_text TEXT NOT NULL,
                from_message_id INTEGER NOT NULL,
                to_message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute("PRAGMA table_info(messages)")
        cols = [str(r[1]) for r in cur.fetchall()]
        if "is_summarized" not in cols:
            cur.execute("ALTER TABLE messages ADD COLUMN is_summarized INTEGER NOT NULL DEFAULT 0")
        if "branch_id" not in cols:
            cur.execute("ALTER TABLE messages ADD COLUMN branch_id INTEGER")

        cur.execute("PRAGMA table_info(summaries)")
        sum_cols = [str(r[1]) for r in cur.fetchall()]
        if "branch_id" not in sum_cols:
            cur.execute("ALTER TABLE summaries ADD COLUMN branch_id INTEGER")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id, id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_branch ON messages(branch_id, id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_branches_chat ON branches(chat_id, id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_summaries_branch ON summaries(branch_id, id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS branch_facts (
                branch_id INTEGER NOT NULL,
                fact_key TEXT NOT NULL,
                fact_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (branch_id, fact_key),
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
            """
        )

        cur.execute("PRAGMA table_info(branches)")
        bcols = [str(r[1]) for r in cur.fetchall()]
        if "memory_strategy" not in bcols:
            cur.execute(
                f"ALTER TABLE branches ADD COLUMN memory_strategy TEXT NOT NULL DEFAULT '{MEMORY_STRATEGY_SUMMARY}'"
            )
        if "strategy_params_json" not in bcols:
            cur.execute(
                "ALTER TABLE branches ADD COLUMN strategy_params_json TEXT NOT NULL DEFAULT '{}'"
            )

        self._migrate_branches_data(cur)
        self._conn.commit()

    def _migrate_branches_data(self, cur: sqlite3.Cursor) -> None:
        cur.execute("SELECT id, system_prompt FROM chats")
        chats = cur.fetchall()
        for r in chats:
            cid = int(r["id"])
            sp = str(r["system_prompt"])
            cur.execute(
                "SELECT id FROM branches WHERE chat_id=? AND parent_branch_id IS NULL LIMIT 1",
                (cid,),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                INSERT INTO branches (
                    chat_id, parent_branch_id, fork_after_message_id, title,
                    system_prompt, temperature, max_tokens, timeout_sec, total_tokens,
                    memory_strategy, strategy_params_json
                )
                VALUES (?, NULL, NULL, 'Основная', ?, ?, ?, ?, 0, ?, '{}')
                """,
                (
                    cid,
                    sp,
                    SETTINGS.default_temperature,
                    SETTINGS.default_max_tokens,
                    SETTINGS.default_timeout_sec,
                    MEMORY_STRATEGY_SUMMARY,
                ),
            )
            bid = int(cur.lastrowid)
            cur.execute(
                "UPDATE messages SET branch_id=? WHERE chat_id=? AND (branch_id IS NULL OR branch_id=0)",
                (bid, cid),
            )

        cur.execute(
            """
            UPDATE messages SET branch_id = (
                SELECT b.id FROM branches b
                WHERE b.chat_id = messages.chat_id AND b.parent_branch_id IS NULL
                LIMIT 1
            )
            WHERE branch_id IS NULL
            """
        )

        cur.execute(
            """
            UPDATE summaries SET branch_id = (
                SELECT m.branch_id FROM messages m WHERE m.id = summaries.from_message_id
            )
            WHERE branch_id IS NULL
            """
        )

    def get_main_branch_id(self, chat_id: int) -> int | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id FROM branches
            WHERE chat_id=? AND parent_branch_id IS NULL
            ORDER BY id ASC LIMIT 1
            """,
            (chat_id,),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else None

    def get_branch(self, branch_id: int) -> BranchInfo | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, chat_id, parent_branch_id, fork_after_message_id, title,
                   system_prompt, temperature, max_tokens, timeout_sec, total_tokens,
                   memory_strategy, strategy_params_json
            FROM branches WHERE id=?
            """,
            (branch_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return BranchInfo(
            branch_id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            parent_branch_id=int(row["parent_branch_id"]) if row["parent_branch_id"] is not None else None,
            fork_after_message_id=int(row["fork_after_message_id"]) if row["fork_after_message_id"] is not None else None,
            title=str(row["title"]),
            system_prompt=str(row["system_prompt"]),
            temperature=float(row["temperature"]),
            max_tokens=int(row["max_tokens"]),
            timeout_sec=float(row["timeout_sec"]),
            total_tokens=int(row["total_tokens"]),
            memory_strategy=str(row["memory_strategy"] or MEMORY_STRATEGY_SUMMARY),
            strategy_params_json=str(row["strategy_params_json"] or "{}"),
        )

    def list_branches(self, chat_id: int) -> list[BranchInfo]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, chat_id, parent_branch_id, fork_after_message_id, title,
                   system_prompt, temperature, max_tokens, timeout_sec, total_tokens,
                   memory_strategy, strategy_params_json
            FROM branches WHERE chat_id=? ORDER BY id ASC
            """,
            (chat_id,),
        )
        out: list[BranchInfo] = []
        for row in cur.fetchall():
            out.append(
                BranchInfo(
                    branch_id=int(row["id"]),
                    chat_id=int(row["chat_id"]),
                    parent_branch_id=int(row["parent_branch_id"]) if row["parent_branch_id"] is not None else None,
                    fork_after_message_id=int(row["fork_after_message_id"]) if row["fork_after_message_id"] is not None else None,
                    title=str(row["title"]),
                    system_prompt=str(row["system_prompt"]),
                    temperature=float(row["temperature"]),
                    max_tokens=int(row["max_tokens"]),
                    timeout_sec=float(row["timeout_sec"]),
                    total_tokens=int(row["total_tokens"]),
                    memory_strategy=str(row["memory_strategy"] or MEMORY_STRATEGY_SUMMARY),
                    strategy_params_json=str(row["strategy_params_json"] or "{}"),
                )
            )
        return out

    def update_branch_settings(
        self,
        branch_id: int,
        *,
        title: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_sec: float | None = None,
        memory_strategy: str | None = None,
        strategy_params_json: str | None = None,
    ) -> None:
        b = self.get_branch(branch_id)
        if not b:
            raise ValueError("Ветка не найдена")
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE branches SET
                title = COALESCE(?, title),
                system_prompt = COALESCE(?, system_prompt),
                temperature = COALESCE(?, temperature),
                max_tokens = COALESCE(?, max_tokens),
                timeout_sec = COALESCE(?, timeout_sec),
                memory_strategy = COALESCE(?, memory_strategy),
                strategy_params_json = COALESCE(?, strategy_params_json)
            WHERE id = ?
            """,
            (
                title,
                system_prompt,
                temperature,
                max_tokens,
                timeout_sec,
                memory_strategy,
                strategy_params_json,
                branch_id,
            ),
        )
        if system_prompt is not None:
            cur.execute(
                """
                UPDATE messages SET content=?
                WHERE id = (
                    SELECT id FROM messages
                    WHERE branch_id=? AND role='system'
                    ORDER BY id ASC LIMIT 1
                )
                """,
                (system_prompt, branch_id),
            )
        cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (b.chat_id,))
        self._conn.commit()

    def fork_branch(
        self,
        *,
        chat_id: int,
        parent_branch_id: int,
        fork_after_message_id: int,
        title: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout_sec: float,
    ) -> int:
        """Копирует историю родителя до fork_after_message_id (включительно) в новую ветку."""
        parent = self.get_branch(parent_branch_id)
        if not parent or parent.chat_id != chat_id:
            raise ValueError("Родительская ветка не найдена")

        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE branch_id=? AND id=? AND chat_id=?
            """,
            (parent_branch_id, fork_after_message_id, chat_id),
        )
        if cur.fetchone()[0] == 0:
            raise ValueError("Сообщение не принадлежит этой ветке")

        cur.execute(
            """
            INSERT INTO branches (
                chat_id, parent_branch_id, fork_after_message_id, title,
                system_prompt, temperature, max_tokens, timeout_sec, total_tokens,
                memory_strategy, strategy_params_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                chat_id,
                parent_branch_id,
                fork_after_message_id,
                title,
                system_prompt,
                temperature,
                max_tokens,
                timeout_sec,
                parent.memory_strategy,
                parent.strategy_params_json,
            ),
        )
        new_bid = int(cur.lastrowid)

        cur.execute(
            """
            SELECT id, role, content FROM messages
            WHERE branch_id=? AND chat_id=? AND id <= ?
            ORDER BY id ASC
            """,
            (parent_branch_id, chat_id, fork_after_message_id),
        )
        for row in cur.fetchall():
            cur.execute(
                """
                INSERT INTO messages (chat_id, branch_id, role, content, is_summarized)
                VALUES (?, ?, ?, ?, 0)
                """,
                (chat_id, new_bid, str(row["role"]), str(row["content"])),
            )

        cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
        self._conn.commit()
        return new_bid

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
            INSERT INTO branches (
                chat_id, parent_branch_id, fork_after_message_id, title,
                system_prompt, temperature, max_tokens, timeout_sec, total_tokens,
                memory_strategy, strategy_params_json
            )
            VALUES (?, NULL, NULL, 'Основная', ?, ?, ?, ?, 0, ?, '{}')
            """,
            (
                chat_id,
                system_prompt,
                SETTINGS.default_temperature,
                SETTINGS.default_max_tokens,
                SETTINGS.default_timeout_sec,
                MEMORY_STRATEGY_SUMMARY,
            ),
        )
        branch_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO messages (chat_id, branch_id, role, content)
            VALUES (?, ?, 'system', ?)
            """,
            (chat_id, branch_id, system_prompt),
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
        cur.execute(
            """
            INSERT INTO branches (
                chat_id, parent_branch_id, fork_after_message_id, title,
                system_prompt, temperature, max_tokens, timeout_sec, total_tokens,
                memory_strategy, strategy_params_json
            )
            VALUES (?, NULL, NULL, 'Основная', ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                chat_id,
                system_prompt,
                SETTINGS.default_temperature,
                SETTINGS.default_max_tokens,
                SETTINGS.default_timeout_sec,
                0,
                MEMORY_STRATEGY_SUMMARY,
            ),
        )
        branch_id = int(cur.lastrowid)
        if messages:
            values = [
                (chat_id, branch_id, str(m.get("role", "")), str(m.get("content", "")))
                for m in messages
            ]
            cur.executemany(
                """
                INSERT INTO messages (chat_id, branch_id, role, content)
                VALUES (?, ?, ?, ?)
                """,
                values,
            )
        self._conn.commit()
        return chat_id

    def get_messages(self, chat_id: int) -> list[dict[str, str]]:
        bid = self.get_main_branch_id(chat_id)
        if bid is None:
            return []
        return self.get_messages_for_branch(bid)

    def get_messages_for_branch(self, branch_id: int) -> list[dict[str, str]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT role, content
            FROM messages
            WHERE branch_id=?
            ORDER BY id ASC
            """,
            (branch_id,),
        )
        rows = cur.fetchall()
        return [{"role": str(r["role"]), "content": str(r["content"])} for r in rows]

    def list_messages_all(self, chat_id: int, branch_id: int | None = None) -> list[MessageRow]:
        if branch_id is None:
            bid = self.get_main_branch_id(chat_id)
            if bid is None:
                return []
            branch_id = bid
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, role, content, is_summarized
            FROM messages
            WHERE branch_id=? AND chat_id=?
            ORDER BY id ASC
            """,
            (branch_id, chat_id),
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

    def get_context_messages(self, branch_id: int) -> list[dict[str, str]]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT chat_id FROM branches WHERE id=?",
            (branch_id,),
        )
        row = cur.fetchone()
        if not row:
            return []
        chat_id = int(row["chat_id"])

        cur.execute(
            """
            SELECT system_prompt FROM branches WHERE id=?
            """,
            (branch_id,),
        )
        sp_row = cur.fetchone()
        system_prompt = str(sp_row["system_prompt"]) if sp_row else ""

        context: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        cur.execute(
            """
            SELECT summary_text
            FROM summaries
            WHERE branch_id=?
            ORDER BY id ASC
            """,
            (branch_id,),
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
            WHERE branch_id=? AND chat_id=? AND role IN ('user', 'assistant') AND is_summarized=0
            ORDER BY id ASC
            """,
            (branch_id, chat_id),
        )
        for r in cur.fetchall():
            context.append({"role": str(r["role"]), "content": str(r["content"])})

        return context

    def get_unsummarized_message_rows(self, branch_id: int) -> list[MessageRow]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, role, content, is_summarized
            FROM messages
            WHERE branch_id=? AND role IN ('user', 'assistant')
            ORDER BY id ASC
            """,
            (branch_id,),
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
        branch_id: int,
        summary_text: str,
        from_message_id: int,
        to_message_id: int,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute("SELECT chat_id FROM branches WHERE id=?", (branch_id,))
        row = cur.fetchone()
        if not row:
            return
        chat_id = int(row["chat_id"])

        cur.execute(
            """
            INSERT INTO summaries (chat_id, branch_id, summary_text, from_message_id, to_message_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, branch_id, summary_text, from_message_id, to_message_id),
        )
        cur.execute(
            """
            UPDATE messages
            SET is_summarized=1
            WHERE branch_id=? AND id>=? AND id<=? AND role IN ('user', 'assistant')
            """,
            (branch_id, from_message_id, to_message_id),
        )
        cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
        self._conn.commit()

    def get_branch_facts_dict(self, branch_id: int) -> dict[str, str]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT fact_key, fact_value FROM branch_facts WHERE branch_id=? ORDER BY fact_key ASC",
            (branch_id,),
        )
        return {str(r["fact_key"]): str(r["fact_value"]) for r in cur.fetchall()}

    def replace_branch_facts(self, branch_id: int, facts: dict[str, str]) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM branch_facts WHERE branch_id=?", (branch_id,))
        for k, v in facts.items():
            cur.execute(
                """
                INSERT INTO branch_facts (branch_id, fact_key, fact_value)
                VALUES (?, ?, ?)
                """,
                (branch_id, str(k), str(v)),
            )
        cur.execute("SELECT chat_id FROM branches WHERE id=?", (branch_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(row["chat_id"]),))
        self._conn.commit()

    def delete_summaries_for_branch(self, branch_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM summaries WHERE branch_id=?", (branch_id,))
        self._conn.commit()

    def delete_old_user_assistant_keep_last(
        self, chat_id: int, branch_id: int, keep_messages: int
    ) -> None:
        """Оставляет последние keep_messages сообщений с ролями user/assistant (по id)."""
        if keep_messages <= 0:
            return
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id FROM messages
            WHERE branch_id=? AND chat_id=? AND role IN ('user', 'assistant')
            ORDER BY id ASC
            """,
            (branch_id, chat_id),
        )
        ids = [int(r["id"]) for r in cur.fetchall()]
        if len(ids) <= keep_messages:
            return
        drop = ids[: -keep_messages]
        placeholders = ",".join("?" * len(drop))
        cur.execute(
            f"DELETE FROM messages WHERE id IN ({placeholders}) AND branch_id=?",
            (*drop, branch_id),
        )
        cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
        self._conn.commit()

    def append_message(self, chat_id: int, branch_id: int, role: str, content: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO messages (chat_id, branch_id, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, branch_id, role, content),
        )
        cur.execute("UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
        self._conn.commit()

    def add_tokens(self, chat_id: int, branch_id: int, delta_tokens: int) -> None:
        if delta_tokens <= 0:
            return
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE branches
            SET total_tokens = total_tokens + ?
            WHERE id=?
            """,
            (delta_tokens, branch_id),
        )
        cur.execute(
            """
            UPDATE chats
            SET total_tokens = total_tokens + ?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (delta_tokens, chat_id),
        )
        self._conn.commit()
