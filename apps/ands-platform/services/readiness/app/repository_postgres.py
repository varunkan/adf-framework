"""Postgres repository adapter (production) — pg8000. Readiness projection."""

from __future__ import annotations

import json
import threading

from ands_shared import utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projections (
    dossier_id TEXT PRIMARY KEY, signals TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


class PostgresProjectionRepository:
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

    def get(self, dossier_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT signals FROM projections WHERE dossier_id = %s",
                        (dossier_id,))
            row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def upsert(self, dossier_id: str, signals: dict) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO projections (dossier_id, signals, updated_at) "
                "VALUES (%s,%s,%s) ON CONFLICT (dossier_id) DO UPDATE SET "
                "signals=excluded.signals, updated_at=excluded.updated_at",
                (dossier_id, json.dumps(signals), utcnow_iso()))
            self._conn.commit()
        return signals

    def all(self) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT dossier_id, signals FROM projections")
            rows = cur.fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}
