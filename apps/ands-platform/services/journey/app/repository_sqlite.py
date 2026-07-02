"""SQLite repository adapter — the guided-session store (dev/test).

The session row carries a first-class ``tenant_id`` column (the owning
workspace) so the list view can partition by tenant without deserialising every
blob. The column is added by an idempotent ALTER migration so pre-tenancy
databases upgrade in place — the same pattern the dossier index uses.
"""

from __future__ import annotations

import json

from ands_shared import SqliteDb, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    tenant_id  TEXT,
    updated_at TEXT NOT NULL
);
"""


def _tenant_of(data: dict) -> str | None:
    return (str(data.get("tenant_id") or "").strip()) or None


class SqliteSessionRepository:
    _MIGRATIONS = (
        # pre-tenancy databases lack the column; ALTER is a no-op error then
        "ALTER TABLE sessions ADD COLUMN tenant_id TEXT",
    )

    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)
        for mig in self._MIGRATIONS:
            try:
                self.db.execute(mig)
            except Exception:
                pass   # column already exists (fresh schema or re-run)

    def create(self, session_id: str, data: dict) -> dict:
        self.db.execute(
            "INSERT INTO sessions (session_id, data, tenant_id, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, json.dumps(data), _tenant_of(data), utcnow_iso()))
        return data

    def get(self, session_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT data FROM sessions WHERE session_id = ?", (session_id,))
        return json.loads(row["data"]) if row else None

    def update(self, session_id: str, data: dict) -> dict:
        self.db.execute(
            "INSERT INTO sessions (session_id, data, tenant_id, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
            "data=excluded.data, tenant_id=excluded.tenant_id, "
            "updated_at=excluded.updated_at",
            (session_id, json.dumps(data), _tenant_of(data), utcnow_iso()))
        return data

    def all(self, tenant_id: str | None = None) -> dict:
        """All sessions, or — when a tenant context is supplied — only the rows
        that tenant owns (foreign/unowned sessions are invisible)."""
        if tenant_id:
            rows = self.db.fetchall(
                "SELECT session_id, data FROM sessions WHERE tenant_id = ?",
                (tenant_id,))
        else:
            rows = self.db.fetchall("SELECT session_id, data FROM sessions")
        return {r["session_id"]: json.loads(r["data"]) for r in rows}
