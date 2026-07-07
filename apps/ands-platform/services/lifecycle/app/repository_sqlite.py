"""SQLite repository adapter for the lifecycle service (dev/test).

The lifecycle aggregate is stored as a JSON blob keyed by dossier_id.
"""

from __future__ import annotations

import json

from ands_shared import SqliteDb, new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lifecycles (
    dossier_id TEXT PRIMARY KEY,
    state      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS correspondence (
    id          TEXT PRIMARY KEY,
    dossier_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    kind_label  TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT,
    direction   TEXT NOT NULL,
    received_at TEXT,
    reference   TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS correspondence_attachments (
    correspondence_id TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data         BLOB NOT NULL,
    sha256       TEXT NOT NULL,
    uploaded_by  TEXT,
    uploaded_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clock_verifications (
    id              TEXT PRIMARY KEY,
    dossier_id      TEXT NOT NULL,
    clock_key       TEXT NOT NULL,
    verified_date   TEXT NOT NULL,
    calculated_date TEXT,
    source_ref      TEXT NOT NULL,
    verified_by     TEXT,
    verified_at     TEXT NOT NULL,
    tenant_id       TEXT
);
CREATE TABLE IF NOT EXISTS noa_allegations (
    id         TEXT PRIMARY KEY,
    dossier_id TEXT NOT NULL,
    record     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shortage_records (
    id         TEXT PRIMARY KEY,
    dossier_id TEXT NOT NULL,
    rtype      TEXT NOT NULL,
    record     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _public(row) -> dict:
    """Strip the internal tenant_id column so response shapes stay identical."""
    rec = dict(row)
    rec.pop("tenant_id", None)
    return rec


class SqliteLifecycleRepository:
    _MIGRATIONS = (
        # pre-tenancy databases lack the column; ALTER is a no-op error then.
        # every client-data table is partitioned by the injecting tenant so a
        # tenant can neither list nor mutate another tenant's rows (CRO
        # isolation guarantee — same contract as the dossier service).
        "ALTER TABLE lifecycles ADD COLUMN tenant_id TEXT",
        "ALTER TABLE correspondence ADD COLUMN tenant_id TEXT",
        "ALTER TABLE noa_allegations ADD COLUMN tenant_id TEXT",
        "ALTER TABLE shortage_records ADD COLUMN tenant_id TEXT",
    )

    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)
        for mig in self._MIGRATIONS:
            try:
                self.db.execute(mig)
            except Exception:
                pass   # column already exists (fresh schema or re-run)

    def save(self, state: dict, tenant_id: str | None = None) -> dict:
        self.db.execute(
            "INSERT INTO lifecycles (dossier_id, state, tenant_id, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(dossier_id) DO UPDATE SET "
            "state=excluded.state, updated_at=excluded.updated_at, "
            # a save never re-homes a lifecycle to another tenant
            "tenant_id=COALESCE(lifecycles.tenant_id, excluded.tenant_id)",
            (state["dossier_id"], json.dumps(state), tenant_id or None,
             utcnow_iso()))
        return state

    def get(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT state FROM lifecycles WHERE dossier_id = ?", (dossier_id,))
        return json.loads(row["state"]) if row else None

    def get_tenant(self, dossier_id: str) -> str | None:
        row = self.db.fetchone(
            "SELECT tenant_id FROM lifecycles WHERE dossier_id = ?",
            (dossier_id,))
        return (row["tenant_id"] if row else None) or None

    def list(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT state FROM lifecycles ORDER BY updated_at")
        return [json.loads(r["state"]) for r in rows]

    # -- HC correspondence (REQ-112) ---------------------------------------
    def add_correspondence(self, record: dict,
                           tenant_id: str | None = None) -> dict:
        cid = new_id()
        self.db.execute(
            "INSERT INTO correspondence (id, dossier_id, kind, kind_label, "
            "subject, body, direction, received_at, reference, tenant_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, record["dossier_id"], record["kind"], record["kind_label"],
             record["subject"], record.get("body"), record["direction"],
             record.get("received_at"), record.get("reference"),
             tenant_id or None, utcnow_iso()))
        return _public(self.db.fetchone(
            "SELECT * FROM correspondence WHERE id = ?", (cid,)))

    def get_correspondence_raw(self, cid: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM correspondence WHERE id = ?", (cid,))
        return dict(row) if row else None

    def put_attachment(self, cid: str, filename: str, content_type: str,
                       data: bytes, sha256: str,
                       uploaded_by: str | None) -> dict:
        self.db.execute(
            "INSERT INTO correspondence_attachments (correspondence_id, "
            "filename, content_type, data, sha256, uploaded_by, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (correspondence_id) DO UPDATE SET "
            "filename = excluded.filename, "
            "content_type = excluded.content_type, data = excluded.data, "
            "sha256 = excluded.sha256, uploaded_by = excluded.uploaded_by, "
            "uploaded_at = excluded.uploaded_at",
            (cid, filename, content_type, data, sha256, uploaded_by,
             utcnow_iso()))
        return self.get_attachment(cid, meta_only=True)  # type: ignore

    def get_attachment(self, cid: str, meta_only: bool = False) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM correspondence_attachments "
            "WHERE correspondence_id = ?", (cid,))
        if not row:
            return None
        rec = dict(row)
        if meta_only:
            rec.pop("data", None)
        return rec

    def list_correspondence(self, dossier_id: str, kind: str = "",
                            tenant_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM correspondence WHERE dossier_id = ?"
        params: list = [dossier_id]
        if str(kind or "").strip():
            sql += " AND kind = ?"
            params.append(kind)
        if tenant_id:   # strict: a tenant sees ONLY its own correspondence
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        rows = self.db.fetchall(sql + " ORDER BY created_at", tuple(params))
        out = []
        for r in rows:
            rec = _public(r)
            att = self.get_attachment(rec["id"], meta_only=True)
            rec["has_attachment"] = att is not None
            rec["attachment_filename"] = att["filename"] if att else None
            rec["attachment_sha256"] = att["sha256"] if att else None
            out.append(rec)
        return out

    # -- verified-date overrides (round-9, operations n=4) -------------------
    # APPEND-ONLY: a re-verification INSERTs a new row; nothing is updated or
    # deleted, so the who/when/source history is inspection-grade.
    def add_verified_date(self, record: dict,
                          tenant_id: str | None = None) -> dict:
        record = dict(record, id=new_id(), verified_at=utcnow_iso())
        self.db.execute(
            "INSERT INTO clock_verifications (id, dossier_id, clock_key, "
            "verified_date, calculated_date, source_ref, verified_by, "
            "verified_at, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record["id"], record["dossier_id"], record["clock_key"],
             record["verified_date"], record.get("calculated_date"),
             record["source_ref"], record.get("verified_by"),
             record["verified_at"], tenant_id or None))
        return record

    def list_verified_dates(self, dossier_id: str,
                            tenant_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM clock_verifications WHERE dossier_id = ?"
        params: list = [dossier_id]
        if tenant_id:   # strict: a tenant sees ONLY its own verifications
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        rows = self.db.fetchall(sql + " ORDER BY verified_at, id",
                                tuple(params))
        return [_public(r) for r in rows]

    # -- Form V / NOA register (PM(NOC) Regulations) -------------------------
    def add_noa(self, record: dict, tenant_id: str | None = None) -> dict:
        record = dict(record, id=new_id())
        now = utcnow_iso()
        self.db.execute(
            "INSERT INTO noa_allegations (id, dossier_id, record, tenant_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record["id"], record["dossier_id"], json.dumps(record),
             tenant_id or None, now, now))
        return record

    def get_noa(self, noa_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT record FROM noa_allegations WHERE id = ?", (noa_id,))
        return json.loads(row["record"]) if row else None

    def get_noa_tenant(self, noa_id: str) -> str | None:
        row = self.db.fetchone(
            "SELECT tenant_id FROM noa_allegations WHERE id = ?", (noa_id,))
        return (row["tenant_id"] if row else None) or None

    def save_noa(self, record: dict) -> dict:
        self.db.execute(
            "UPDATE noa_allegations SET record = ?, updated_at = ? "
            "WHERE id = ?", (json.dumps(record), utcnow_iso(), record["id"]))
        return record

    def list_noa(self, dossier_id: str,
                 tenant_id: str | None = None) -> list[dict]:
        sql = "SELECT record FROM noa_allegations WHERE dossier_id = ?"
        params: list = [dossier_id]
        if tenant_id:   # strict: a tenant sees ONLY its own allegations
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        rows = self.db.fetchall(sql + " ORDER BY created_at", tuple(params))
        return [json.loads(r["record"]) for r in rows]

    # -- drug shortage / discontinuation + DEL linkage -----------------------
    _RT_SHORTAGE = "shortage_report"
    _RT_DEL = "del_link"

    def _add_shortage_record(self, rtype: str, record: dict,
                             tenant_id: str | None = None) -> dict:
        record = dict(record, id=new_id())
        self.db.execute(
            "INSERT INTO shortage_records (id, dossier_id, rtype, record, "
            "tenant_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record["id"], record["dossier_id"], rtype, json.dumps(record),
             tenant_id or None, utcnow_iso()))
        return record

    def _list_shortage_records(self, rtype: str, dossier_id: str,
                               tenant_id: str | None = None) -> list[dict]:
        sql = ("SELECT record FROM shortage_records WHERE dossier_id = ? "
               "AND rtype = ?")
        params: list = [dossier_id, rtype]
        if tenant_id:   # strict: a tenant sees ONLY its own reports/links
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        rows = self.db.fetchall(sql + " ORDER BY created_at", tuple(params))
        return [json.loads(r["record"]) for r in rows]

    def add_shortage(self, record: dict, tenant_id: str | None = None) -> dict:
        return self._add_shortage_record(self._RT_SHORTAGE, record, tenant_id)

    def list_shortage(self, dossier_id: str,
                      tenant_id: str | None = None) -> list[dict]:
        return self._list_shortage_records(self._RT_SHORTAGE, dossier_id,
                                           tenant_id)

    def add_del_link(self, record: dict, tenant_id: str | None = None) -> dict:
        return self._add_shortage_record(self._RT_DEL, record, tenant_id)

    def list_del_links(self, dossier_id: str,
                       tenant_id: str | None = None) -> list[dict]:
        return self._list_shortage_records(self._RT_DEL, dossier_id, tenant_id)
