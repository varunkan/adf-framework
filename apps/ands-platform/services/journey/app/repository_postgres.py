"""Postgres repository adapter (production) — pg8000. Guided-session store.

Carries a first-class ``tenant_id`` column so ``all()`` can partition by tenant
(the same contract as the SQLite adapter). The column is added by an idempotent
ALTER migration so pre-tenancy databases upgrade in place.
"""

from __future__ import annotations

import json
import threading

from ands_shared import utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
"""

# pre-tenancy databases lack the column; ALTER is a no-op error then
_MIGRATIONS = ("ALTER TABLE sessions ADD COLUMN tenant_id TEXT",)


def _tenant_of(data: dict) -> str | None:
    return (str(data.get("tenant_id") or "").strip()) or None


class PostgresSessionRepository:
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

    def create(self, session_id: str, data: dict) -> dict:
        return self.update(session_id, data)

    def get(self, session_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT data FROM sessions WHERE session_id = %s",
                        (session_id,))
            row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def update(self, session_id: str, data: dict) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO sessions (session_id, data, tenant_id, updated_at) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (session_id) DO UPDATE SET "
                "data=excluded.data, tenant_id=excluded.tenant_id, "
                "updated_at=excluded.updated_at",
                (session_id, json.dumps(data), _tenant_of(data), utcnow_iso()))
            self._conn.commit()
        return data

    def all(self, tenant_id: str | None = None) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            if tenant_id:
                cur.execute("SELECT session_id, data FROM sessions "
                            "WHERE tenant_id = %s", (tenant_id,))
            else:
                cur.execute("SELECT session_id, data FROM sessions")
            rows = cur.fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}
