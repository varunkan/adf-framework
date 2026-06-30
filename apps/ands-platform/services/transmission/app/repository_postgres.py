"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import json
import threading

from ands_shared import utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledgers (
    dossier_id TEXT PRIMARY KEY, ledger TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


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
            self._conn.commit()

    def save(self, ledger: dict) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO ledgers (dossier_id, ledger, updated_at) "
                "VALUES (%s,%s,%s) ON CONFLICT (dossier_id) DO UPDATE SET "
                "ledger=excluded.ledger, updated_at=excluded.updated_at",
                (ledger["dossier_id"], json.dumps(ledger), utcnow_iso()))
            self._conn.commit()
        return ledger

    def get(self, dossier_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT ledger FROM ledgers WHERE dossier_id = %s",
                        (dossier_id,))
            row = cur.fetchone()
        return json.loads(row[0]) if row else None
