"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import json
import threading

from ands_shared import new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_runs (
    id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, sequence TEXT NOT NULL,
    ruleset_version TEXT NOT NULL, blocking INTEGER NOT NULL,
    error_count INTEGER NOT NULL, warning_count INTEGER NOT NULL,
    result TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS validation_jobs (
    id TEXT PRIMARY KEY, status TEXT NOT NULL, result TEXT NOT NULL,
    created_at TEXT NOT NULL);
"""


class PostgresValidationRepository:
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

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            self._conn.commit()
            return cur

    def _one(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

    def _hydrate(self, rec):
        if rec:
            rec["blocking"] = bool(rec["blocking"])
            rec["result"] = json.loads(rec["result"])
        return rec

    def save_run(self, dossier_id, sequence, result) -> dict:
        rid, created = new_id(), utcnow_iso()
        self._exec(
            "INSERT INTO validation_runs (id, dossier_id, sequence, "
            "ruleset_version, blocking, error_count, warning_count, result, "
            "created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (rid, dossier_id, sequence, result.get("ruleset_version", ""),
             1 if result.get("blocking") else 0, result.get("error_count", 0),
             result.get("warning_count", 0), json.dumps(result), created))
        return self.get_run(rid)

    def get_run(self, run_id) -> dict | None:
        return self._hydrate(self._one(
            "SELECT * FROM validation_runs WHERE id = %s", (run_id,)))

    def latest_run(self, dossier_id, sequence) -> dict | None:
        return self._hydrate(self._one(
            "SELECT * FROM validation_runs WHERE dossier_id = %s AND "
            "sequence = %s ORDER BY created_at DESC, id DESC LIMIT 1",
            (dossier_id, sequence)))

    def save_job(self, result: dict) -> dict:
        jid = new_id()
        self._exec("INSERT INTO validation_jobs (id, status, result, "
                   "created_at) VALUES (%s,'complete',%s,%s)",
                   (jid, json.dumps(result), utcnow_iso()))
        return self.get_job(jid)

    def get_job(self, job_id: str) -> dict | None:
        rec = self._one("SELECT * FROM validation_jobs WHERE id = %s", (job_id,))
        if rec:
            rec["result"] = json.loads(rec["result"])
        return rec
