"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import threading

from ands_shared import new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registrations (
    id TEXT PRIMARY KEY, product TEXT NOT NULL, country TEXT NOT NULL,
    dossier_id TEXT NOT NULL, din TEXT, drug_type TEXT, status TEXT NOT NULL,
    tenant_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""

# pre-tenancy databases lack the column; ALTER is a no-op error then
_MIGRATIONS = ("ALTER TABLE registrations ADD COLUMN tenant_id TEXT",)

_FILTERS = ("product", "country", "din", "status", "dossier_id")


class PostgresRegistrationRepository:
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

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def add(self, registration: dict) -> dict:
        rid, now = new_id(), utcnow_iso()
        self._exec(
            "INSERT INTO registrations (id, product, country, dossier_id, din, "
            "drug_type, status, tenant_id, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (rid, registration["product"], registration["country"],
             registration["dossier_id"], registration.get("din"),
             registration.get("drug_type"), registration["status"],
             registration.get("tenant_id") or None, now, now))
        return self.get(rid)

    def get(self, reg_id: str) -> dict | None:
        rows = self._all("SELECT * FROM registrations WHERE id = %s", (reg_id,))
        return rows[0] if rows else None

    def list(self, *, product="", country="", din="", status="",
             dossier_id="", tenant_id="") -> list[dict]:
        vals = {"product": product, "country": country, "din": din,
                "status": status, "dossier_id": dossier_id}
        clauses, params = [], []
        for col in _FILTERS:
            if str(vals[col] or "").strip():
                clauses.append(f"{col} = %s")
                params.append(str(vals[col]).strip())
        if str(tenant_id or "").strip():
            clauses.append("tenant_id = %s")   # CRO isolation: own rows only
            params.append(str(tenant_id).strip())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._all("SELECT * FROM registrations" + where
                         + " ORDER BY created_at, id", tuple(params))

    def set_status(self, reg_id: str, status: str) -> dict | None:
        self._exec("UPDATE registrations SET status = %s, updated_at = %s "
                   "WHERE id = %s", (status, utcnow_iso(), reg_id))
        return self.get(reg_id)
