"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import json
import threading

from ands_shared import utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledgers (
    dossier_id TEXT PRIMARY KEY, ledger TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
"""

# pre-tenancy databases lack the column; ALTER is a no-op error then.
_MIGRATIONS = (
    "ALTER TABLE ledgers ADD COLUMN IF NOT EXISTS tenant_id "
    "TEXT NOT NULL DEFAULT ''",
)


class PostgresTransmissionRepository:
    def __init__(self, dsn: str) -> None:
        import pg8000.dbapi
        from urllib.parse import urlparse
        u = urlparse(dsn)
        self._conn = pg8000.dbapi.connect(
            user=u.username, password=u.password, host=u.hostname,
            port=u.port or 5432, database=(u.path or "/").lstrip("/"))
        self._lock = threading.Lock()
        with self._lock:
            cur = self._conn.cursor()
            for stmt in filter(str.strip, _SCHEMA.split(";")):
                cur.execute(stmt)
            for mig in _MIGRATIONS:
                try:
                    cur.execute(mig)
                except Exception:
                    self._conn.rollback()   # column already exists
            self._conn.commit()

    def save(self, ledger: dict, tenant_id: str = "") -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO ledgers (dossier_id, ledger, tenant_id, "
                "updated_at) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (dossier_id) DO UPDATE SET "
                "ledger=excluded.ledger, updated_at=excluded.updated_at, "
                "tenant_id=CASE WHEN excluded.tenant_id != '' "
                "THEN excluded.tenant_id ELSE ledgers.tenant_id END",
                (ledger["dossier_id"], json.dumps(ledger),
                 str(tenant_id or "").strip(), utcnow_iso()))
            self._conn.commit()
        return ledger

    def get(self, dossier_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT ledger, tenant_id FROM ledgers WHERE dossier_id = %s",
                (dossier_id,))
            row = cur.fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        data["_tenant_id"] = row[1] or ""
        return data
