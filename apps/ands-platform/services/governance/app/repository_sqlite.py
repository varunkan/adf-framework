"""SQLite repository adapter — the append-only audit trail (dev/test).

There is NO update or delete path: the trail cannot be redacted (REQ-060).
"""

from __future__ import annotations

import json

from ands_shared import SqliteDb, new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id         TEXT PRIMARY KEY,
    at         TEXT NOT NULL,
    category   TEXT NOT NULL,
    action     TEXT NOT NULL,
    dossier_id TEXT NOT NULL DEFAULT '',
    tenant_id  TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '{}',
    seq        INTEGER
);
CREATE TABLE IF NOT EXISTS legal_holds (
    tenant_id  TEXT PRIMARY KEY,
    active     INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SqliteAuditRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    def append(self, event: dict) -> dict:
        eid = new_id()
        at = str(event.get("at") or "").strip() or utcnow_iso()
        self.db.execute(
            "INSERT INTO audit_events (id, at, category, action, dossier_id, "
            "tenant_id, detail, seq) VALUES (?, ?, ?, ?, ?, ?, ?, "
            "(SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_events))",
            (eid, at, str(event.get("category") or ""),
             str(event.get("action") or ""), str(event.get("dossier_id") or ""),
             str(event.get("tenant_id") or ""),
             json.dumps(event.get("detail") or {})))
        return self._row(eid)

    def _row(self, eid: str) -> dict:
        rec = dict(self.db.fetchone(
            "SELECT * FROM audit_events WHERE id = ?", (eid,)))
        rec["detail"] = json.loads(rec["detail"])
        return rec

    def list(self, *, category: str = "", dossier_id: str = "",
             tenant_id: str = "") -> list[dict]:
        clauses, params = [], []
        for col, val in (("category", category), ("dossier_id", dossier_id),
                         ("tenant_id", tenant_id)):
            if str(val or "").strip():
                clauses.append(f"{col} = ?")   # col is a hardcoded literal
                params.append(str(val).strip())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.fetchall(
            "SELECT * FROM audit_events" + where + " ORDER BY seq", tuple(params))
        out = []
        for r in rows:
            rec = dict(r)
            rec["detail"] = json.loads(rec["detail"])
            out.append(rec)
        return out

    def count(self) -> int:
        return int(self.db.fetchone(
            "SELECT COUNT(*) AS n FROM audit_events")["n"])

    # -- legal holds (SAAS-REQ-004) ----------------------------------------
    def set_legal_hold(self, tenant_id: str, active: bool) -> None:
        self.db.execute(
            "INSERT INTO legal_holds (tenant_id, active, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(tenant_id) DO UPDATE SET "
            "active=excluded.active, updated_at=excluded.updated_at",
            (tenant_id, 1 if active else 0, utcnow_iso()))

    def get_legal_hold(self, tenant_id: str) -> bool:
        row = self.db.fetchone(
            "SELECT active FROM legal_holds WHERE tenant_id = ?", (tenant_id,))
        return bool(row["active"]) if row else False
