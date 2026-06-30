"""SQLite repository adapter for the transmission service (dev/test)."""

from __future__ import annotations

import json

from ands_shared import SqliteDb, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledgers (
    dossier_id TEXT PRIMARY KEY,
    ledger     TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SqliteTransmissionRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    def save(self, ledger: dict) -> dict:
        self.db.execute(
            "INSERT INTO ledgers (dossier_id, ledger, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(dossier_id) DO UPDATE SET "
            "ledger=excluded.ledger, updated_at=excluded.updated_at",
            (ledger["dossier_id"], json.dumps(ledger), utcnow_iso()))
        return ledger

    def get(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT ledger FROM ledgers WHERE dossier_id = ?", (dossier_id,))
        return json.loads(row["ledger"]) if row else None
