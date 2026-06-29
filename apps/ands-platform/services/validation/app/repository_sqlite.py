"""SQLite repository adapter for the validation service (dev/test)."""

from __future__ import annotations

import json

from ands_shared import SqliteDb, new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_runs (
    id              TEXT PRIMARY KEY,
    dossier_id      TEXT NOT NULL,
    sequence        TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    blocking        INTEGER NOT NULL,
    error_count     INTEGER NOT NULL,
    warning_count   INTEGER NOT NULL,
    result          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""


class SqliteValidationRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    def save_run(self, dossier_id: str, sequence: str, result: dict) -> dict:
        rid = new_id()
        created = utcnow_iso()
        self.db.execute(
            "INSERT INTO validation_runs (id, dossier_id, sequence, "
            "ruleset_version, blocking, error_count, warning_count, result, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, dossier_id, sequence, result.get("ruleset_version", ""),
             1 if result.get("blocking") else 0, result.get("error_count", 0),
             result.get("warning_count", 0), json.dumps(result), created))
        return self.get_run(rid)

    def _hydrate(self, row) -> dict:
        rec = dict(row)
        rec["blocking"] = bool(rec["blocking"])
        rec["result"] = json.loads(rec["result"])
        return rec

    def get_run(self, run_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM validation_runs WHERE id = ?", (run_id,))
        return self._hydrate(row) if row else None

    def latest_run(self, dossier_id: str, sequence: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM validation_runs WHERE dossier_id = ? AND sequence = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1", (dossier_id, sequence))
        return self._hydrate(row) if row else None
