"""SQLite repository adapter — the per-dossier readiness projection (dev/test)."""

from __future__ import annotations

import json

from ands_shared import SqliteDb, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projections (
    dossier_id TEXT PRIMARY KEY,
    signals    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SqliteProjectionRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    def get(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT signals FROM projections WHERE dossier_id = ?", (dossier_id,))
        return json.loads(row["signals"]) if row else None

    def upsert(self, dossier_id: str, signals: dict) -> dict:
        self.db.execute(
            "INSERT INTO projections (dossier_id, signals, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(dossier_id) DO UPDATE SET "
            "signals=excluded.signals, updated_at=excluded.updated_at",
            (dossier_id, json.dumps(signals), utcnow_iso()))
        return signals

    def all(self) -> dict:
        rows = self.db.fetchall("SELECT dossier_id, signals FROM projections")
        return {r["dossier_id"]: json.loads(r["signals"]) for r in rows}
