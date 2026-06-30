"""SQLite repository adapter — the guided-session store (dev/test)."""

from __future__ import annotations

import json

from ands_shared import SqliteDb, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SqliteSessionRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    def create(self, session_id: str, data: dict) -> dict:
        self.db.execute(
            "INSERT INTO sessions (session_id, data, updated_at) VALUES (?, ?, ?)",
            (session_id, json.dumps(data), utcnow_iso()))
        return data

    def get(self, session_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT data FROM sessions WHERE session_id = ?", (session_id,))
        return json.loads(row["data"]) if row else None

    def update(self, session_id: str, data: dict) -> dict:
        self.db.execute(
            "INSERT INTO sessions (session_id, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET data=excluded.data, "
            "updated_at=excluded.updated_at",
            (session_id, json.dumps(data), utcnow_iso()))
        return data

    def all(self) -> dict:
        rows = self.db.fetchall("SELECT session_id, data FROM sessions")
        return {r["session_id"]: json.loads(r["data"]) for r in rows}
