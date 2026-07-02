"""SQLite repository adapter for the transmission service (dev/test)."""

from __future__ import annotations

import json

from ands_shared import SqliteDb, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledgers (
    dossier_id TEXT PRIMARY KEY,
    ledger     TEXT NOT NULL,
    tenant_id  TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""

# pre-tenancy databases lack the column; ALTER is a no-op error then (same
# try/except migration pattern the dossier service's repository_sqlite uses).
_MIGRATIONS = (
    "ALTER TABLE ledgers ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''",
)


class SqliteTransmissionRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)
        for mig in _MIGRATIONS:
            try:
                self.db.execute(mig)
            except Exception:
                pass   # column already exists (fresh schema or re-run)

    def save(self, ledger: dict, tenant_id: str = "") -> dict:
        # First writer owns the ledger; later unscoped saves (empty tenant_id)
        # must not blank an existing owner -> COALESCE-style keep on conflict.
        self.db.execute(
            "INSERT INTO ledgers (dossier_id, ledger, tenant_id, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(dossier_id) DO UPDATE SET "
            "ledger=excluded.ledger, updated_at=excluded.updated_at, "
            "tenant_id=CASE WHEN excluded.tenant_id != '' "
            "THEN excluded.tenant_id ELSE ledgers.tenant_id END",
            (ledger["dossier_id"], json.dumps(ledger),
             str(tenant_id or "").strip(), utcnow_iso()))
        return ledger

    def get(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT ledger, tenant_id FROM ledgers WHERE dossier_id = ?",
            (dossier_id,))
        if not row:
            return None
        data = json.loads(row["ledger"])
        # surface ownership to the service guard without polluting the ledger's
        # public shape (kept under a private key the API strips before return).
        data["_tenant_id"] = row["tenant_id"] or ""
        return data
