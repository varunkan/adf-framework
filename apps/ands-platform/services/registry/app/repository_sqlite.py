"""SQLite repository adapter for the registry service (dev/test)."""

from __future__ import annotations

from ands_shared import SqliteDb, new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registrations (
    id         TEXT PRIMARY KEY,
    product    TEXT NOT NULL,
    country    TEXT NOT NULL,
    dossier_id TEXT NOT NULL,
    din        TEXT,
    drug_type  TEXT,
    status     TEXT NOT NULL,
    tenant_id  TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS annual_checklist (
    tenant_id TEXT NOT NULL,
    year      INTEGER NOT NULL,
    item_key  TEXT NOT NULL,
    done      INTEGER NOT NULL DEFAULT 0,
    signed_by TEXT,
    signed_at TEXT,
    meaning   TEXT,
    reauthenticated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, year, item_key)
);
CREATE TABLE IF NOT EXISTS annual_checklist_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    year      INTEGER NOT NULL,
    item_key  TEXT NOT NULL,
    action    TEXT NOT NULL,
    signed_by TEXT,
    signed_at TEXT NOT NULL,
    meaning   TEXT,
    reauthenticated INTEGER NOT NULL DEFAULT 0
);
"""

_FILTERS = ("product", "country", "din", "status", "dossier_id")


class SqliteRegistrationRepository:
    _MIGRATIONS = (
        # pre-tenancy databases lack the column; ALTER is a no-op error then
        "ALTER TABLE registrations ADD COLUMN tenant_id TEXT",
        "ALTER TABLE annual_checklist ADD COLUMN meaning TEXT",
        "ALTER TABLE annual_checklist ADD COLUMN reauthenticated INTEGER NOT NULL DEFAULT 0",
    )

    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)
        for mig in self._MIGRATIONS:
            try:
                self.db.execute(mig)
            except Exception:
                pass   # column already exists (fresh schema or re-run)

    def add(self, registration: dict) -> dict:
        rid = new_id()
        now = utcnow_iso()
        self.db.execute(
            "INSERT INTO registrations (id, product, country, dossier_id, din, "
            "drug_type, status, tenant_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, registration["product"], registration["country"],
             registration["dossier_id"], registration.get("din"),
             registration.get("drug_type"), registration["status"],
             registration.get("tenant_id") or None, now, now))
        return self.get(rid)

    def get(self, reg_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM registrations WHERE id = ?", (reg_id,))
        return dict(row) if row else None

    def list(self, *, product="", country="", din="", status="",
             dossier_id="", tenant_id="") -> list[dict]:
        vals = {"product": product, "country": country, "din": din,
                "status": status, "dossier_id": dossier_id}
        clauses, params = [], []
        for col in _FILTERS:
            if str(vals[col] or "").strip():
                clauses.append(f"{col} = ?")   # col is a hardcoded literal
                params.append(str(vals[col]).strip())
        if str(tenant_id or "").strip():
            # strict: a tenant sees ONLY its own rows (unowned/other-tenant
            # registrations are invisible — the CRO isolation guarantee)
            clauses.append("tenant_id = ?")
            params.append(str(tenant_id).strip())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.fetchall(
            "SELECT * FROM registrations" + where + " ORDER BY created_at, id",
            tuple(params))
        return [dict(r) for r in rows]

    def set_status(self, reg_id: str, status: str) -> dict | None:
        self.db.execute(
            "UPDATE registrations SET status = ?, updated_at = ? WHERE id = ?",
            (status, utcnow_iso(), reg_id))
        return self.get(reg_id)

    def get_checklist(self, tenant_id: str, year: int) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM annual_checklist WHERE tenant_id = ? AND year = ?",
            (tenant_id or "", int(year)))
        return [dict(r) for r in rows]

    def set_checklist_item(self, tenant_id: str, year: int, item_key: str,
                           done: bool, signed_by: str | None,
                           signed_at: str | None, meaning: str | None = None,
                           reauthenticated: bool = False) -> dict:
        self.db.execute(
            "INSERT INTO annual_checklist (tenant_id, year, item_key, done, "
            "signed_by, signed_at, meaning, reauthenticated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (tenant_id, year, item_key) DO UPDATE SET "
            "done = excluded.done, signed_by = excluded.signed_by, "
            "signed_at = excluded.signed_at, meaning = excluded.meaning, "
            "reauthenticated = excluded.reauthenticated",
            (tenant_id or "", int(year), item_key, 1 if done else 0,
             signed_by, signed_at, meaning, 1 if reauthenticated else 0))
        # append-only signing record — never updated, never deleted
        self.db.execute(
            "INSERT INTO annual_checklist_log (tenant_id, year, item_key, "
            "action, signed_by, signed_at, meaning, reauthenticated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id or "", int(year), item_key,
             "sign" if done else "unsign", signed_by,
             signed_at or utcnow_iso(),
             meaning, 1 if reauthenticated else 0))
        row = self.db.fetchone(
            "SELECT * FROM annual_checklist WHERE tenant_id = ? AND year = ? "
            "AND item_key = ?", (tenant_id or "", int(year), item_key))
        return dict(row)

    def get_checklist_log(self, tenant_id: str, year: int) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM annual_checklist_log WHERE tenant_id = ? AND "
            "year = ? ORDER BY id", (tenant_id or "", int(year)))
        return [dict(r) for r in rows]
