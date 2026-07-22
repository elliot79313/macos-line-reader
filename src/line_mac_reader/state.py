"""Per-chat last-read state in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_state (
    chat_key     TEXT PRIMARY KEY,
    last_read_at TEXT NOT NULL,   -- ISO8601 with timezone
    updated_at   TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get_last_read(self, chat_key: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_read_at FROM chat_state WHERE chat_key = ?", (chat_key,)
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def set_last_read(self, chat_key: str, when: datetime) -> None:
        now = datetime.now(when.tzinfo).isoformat()
        self._conn.execute(
            "INSERT INTO chat_state (chat_key, last_read_at, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(chat_key) DO UPDATE SET "
            "last_read_at = excluded.last_read_at, updated_at = excluded.updated_at",
            (chat_key, when.isoformat(), now),
        )
        self._conn.commit()

    def reset(self) -> None:
        self._conn.execute("DELETE FROM chat_state")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
