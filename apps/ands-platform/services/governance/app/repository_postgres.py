"""Postgres repository adapter (production) — pg8000. Append-only audit trail."""

from __future__ import annotations

import json
import threading

from ands_shared import new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY, at TEXT NOT NULL, category TEXT NOT NULL,
    action TEXT NOT NULL, dossier_id TEXT NOT NULL DEFAULT '',
    tenant_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '{}',
    seq BIGSERIAL);
"""


class PostgresAuditRepository:
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

    def _all(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def append(self, event: dict) -> dict:
        eid = new_id()
        at = str(event.get("at") or "").strip() or utcnow_iso()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO audit_events (id, at, category, action, dossier_id, "
                "tenant_id, detail) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (eid, at, str(event.get("category") or ""),
                 str(event.get("action") or ""),
                 str(event.get("dossier_id") or ""),
                 str(event.get("tenant_id") or ""),
                 json.dumps(event.get("detail") or {})))
            self._conn.commit()
        rows = self._all("SELECT * FROM audit_events WHERE id = %s", (eid,))
        rec = rows[0]
        rec["detail"] = json.loads(rec["detail"])
        return rec

    def list(self, *, category: str = "", dossier_id: str = "") -> list[dict]:
        clauses, params = [], []
        for col, val in (("category", category), ("dossier_id", dossier_id)):
            if str(val or "").strip():
                clauses.append(f"{col} = %s")
                params.append(str(val).strip())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._all("SELECT * FROM audit_events" + where + " ORDER BY seq",
                         tuple(params))
        for r in rows:
            r["detail"] = json.loads(r["detail"])
        return rows

    def count(self) -> int:
        return int(self._all("SELECT COUNT(*) AS n FROM audit_events")[0]["n"])
