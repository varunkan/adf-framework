"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import json
import threading

from ands_shared import utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lifecycles (
    dossier_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


class PostgresLifecycleRepository:
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

    def save(self, state: dict) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO lifecycles (dossier_id, state, updated_at) "
                "VALUES (%s,%s,%s) ON CONFLICT (dossier_id) DO UPDATE SET "
                "state=excluded.state, updated_at=excluded.updated_at",
                (state["dossier_id"], json.dumps(state), utcnow_iso()))
            self._conn.commit()
        return state

    def get(self, dossier_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT state FROM lifecycles WHERE dossier_id = %s",
                        (dossier_id,))
            row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def list(self) -> list[dict]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT state FROM lifecycles ORDER BY updated_at")
            rows = cur.fetchall()
        return [json.loads(r[0]) for r in rows]
