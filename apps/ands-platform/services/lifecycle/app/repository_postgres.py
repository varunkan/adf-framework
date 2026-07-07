"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import json
import threading

from ands_shared import new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lifecycles (
    dossier_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS correspondence (
    id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, kind TEXT NOT NULL,
    kind_label TEXT NOT NULL, subject TEXT NOT NULL, body TEXT,
    direction TEXT NOT NULL, received_at TEXT, reference TEXT,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS correspondence_attachments (
    correspondence_id TEXT PRIMARY KEY, filename TEXT NOT NULL,
    content_type TEXT NOT NULL, data BYTEA NOT NULL, sha256 TEXT NOT NULL,
    uploaded_by TEXT, uploaded_at TEXT NOT NULL);
"""

# pre-tenancy databases lack the column; ALTER IF NOT EXISTS is idempotent.
# NOTE: this adapter only implements lifecycles + correspondence today; the
# NOA / shortage / DEL tables live only in the SQLite adapter (used in dev +
# tests). When those are ported here they must carry a tenant_id column too.
_MIGRATIONS = (
    "ALTER TABLE lifecycles ADD COLUMN IF NOT EXISTS tenant_id TEXT",
    "ALTER TABLE correspondence ADD COLUMN IF NOT EXISTS tenant_id TEXT",
)


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
            for mig in _MIGRATIONS:
                try:
                    cur.execute(mig)
                except Exception:
                    pass   # column already exists
            self._conn.commit()

    def save(self, state: dict, tenant_id: str | None = None) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO lifecycles (dossier_id, state, tenant_id, "
                "updated_at) VALUES (%s,%s,%s,%s) ON CONFLICT (dossier_id) DO "
                "UPDATE SET state=excluded.state, "
                "updated_at=excluded.updated_at, "
                "tenant_id=COALESCE(lifecycles.tenant_id, excluded.tenant_id)",
                (state["dossier_id"], json.dumps(state), tenant_id or None,
                 utcnow_iso()))
            self._conn.commit()
        return state

    def get_tenant(self, dossier_id: str) -> str | None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT tenant_id FROM lifecycles WHERE dossier_id = %s",
                        (dossier_id,))
            row = cur.fetchone()
        return (row[0] if row else None) or None

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

    # -- HC correspondence (REQ-112) ---------------------------------------
    def _all(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def add_correspondence(self, record: dict,
                           tenant_id: str | None = None) -> dict:
        cid = new_id()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO correspondence (id, dossier_id, kind, kind_label, "
                "subject, body, direction, received_at, reference, tenant_id, "
                "created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (cid, record["dossier_id"], record["kind"], record["kind_label"],
                 record["subject"], record.get("body"), record["direction"],
                 record.get("received_at"), record.get("reference"),
                 tenant_id or None, utcnow_iso()))
            self._conn.commit()
        row = self._all("SELECT * FROM correspondence WHERE id = %s", (cid,))[0]
        row.pop("tenant_id", None)   # keep the public response shape identical
        return row

    def get_correspondence_raw(self, cid: str) -> dict | None:
        rows = self._all("SELECT * FROM correspondence WHERE id = %s", (cid,))
        return rows[0] if rows else None

    def put_attachment(self, cid: str, filename: str, content_type: str,
                       data: bytes, sha256: str,
                       uploaded_by: str | None) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO correspondence_attachments (correspondence_id, "
                "filename, content_type, data, sha256, uploaded_by, "
                "uploaded_at) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (correspondence_id) DO UPDATE SET "
                "filename = EXCLUDED.filename, "
                "content_type = EXCLUDED.content_type, data = EXCLUDED.data, "
                "sha256 = EXCLUDED.sha256, "
                "uploaded_by = EXCLUDED.uploaded_by, "
                "uploaded_at = EXCLUDED.uploaded_at",
                (cid, filename, content_type, data, sha256, uploaded_by,
                 utcnow_iso()))
            self._conn.commit()
        return self.get_attachment(cid, meta_only=True)  # type: ignore

    def get_attachment(self, cid: str, meta_only: bool = False) -> dict | None:
        rows = self._all(
            "SELECT * FROM correspondence_attachments "
            "WHERE correspondence_id = %s", (cid,))
        if not rows:
            return None
        rec = rows[0]
        if meta_only:
            rec.pop("data", None)
        elif isinstance(rec.get("data"), memoryview):
            rec["data"] = bytes(rec["data"])
        return rec

    def list_correspondence(self, dossier_id: str, kind: str = "",
                            tenant_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM correspondence WHERE dossier_id = %s"
        params: list = [dossier_id]
        if str(kind or "").strip():
            sql += " AND kind = %s"
            params.append(kind)
        if tenant_id:
            sql += " AND tenant_id = %s"
            params.append(tenant_id)
        rows = self._all(sql + " ORDER BY created_at", tuple(params))
        for r in rows:
            r.pop("tenant_id", None)
            att = self.get_attachment(r["id"], meta_only=True)
            r["has_attachment"] = att is not None
            r["attachment_filename"] = att["filename"] if att else None
            r["attachment_sha256"] = att["sha256"] if att else None
        return rows
