"""SQLite repository adapter for the lifecycle service (dev/test).

The lifecycle aggregate is stored as a JSON blob keyed by dossier_id.
"""

from __future__ import annotations

import json

from ands_shared import SqliteDb, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lifecycles (
    dossier_id TEXT PRIMARY KEY,
    state      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SqliteLifecycleRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    def save(self, state: dict) -> dict:
        self.db.execute(
            "INSERT INTO lifecycles (dossier_id, state, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(dossier_id) DO UPDATE SET "
            "state=excluded.state, updated_at=excluded.updated_at",
            (state["dossier_id"], json.dumps(state), utcnow_iso()))
        return state

    def get(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT state FROM lifecycles WHERE dossier_id = ?", (dossier_id,))
        return json.loads(row["state"]) if row else None

    def list(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT state FROM lifecycles ORDER BY updated_at")
        return [json.loads(r["state"]) for r in rows]
