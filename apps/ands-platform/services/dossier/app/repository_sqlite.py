"""SQLite repository adapter for the dossier service (dev/test)."""

from __future__ import annotations

import json

from ands_shared import SqliteDb, new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_plans (
    id              TEXT PRIMARY KEY,
    dossier_id      TEXT NOT NULL,
    submission_type TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_plan_items (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL,
    dossier_id  TEXT NOT NULL,
    ord         INTEGER NOT NULL,
    key         TEXT NOT NULL,
    title       TEXT NOT NULL,
    section     TEXT NOT NULL,
    leaf_id     TEXT,
    required    INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL,
    assignee    TEXT,
    due_date    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pm_leaves (
    dossier_id  TEXT NOT NULL,
    lang        TEXT NOT NULL,
    leaf_id     TEXT NOT NULL,
    title       TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    heading     TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (dossier_id, lang)
);
CREATE TABLE IF NOT EXISTS dossiers (
    dossier_id  TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS binders (
    id          TEXT PRIMARY KEY,
    dossier_id  TEXT NOT NULL,
    sequence    TEXT NOT NULL,
    binder      TEXT NOT NULL,
    share_token TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    dossier_id   TEXT NOT NULL,
    section      TEXT NOT NULL,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL,
    checksum     TEXT NOT NULL,
    size         INTEGER NOT NULL,
    origin       TEXT NOT NULL,
    lang         TEXT,
    body         BLOB NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS section_state (
    dossier_id  TEXT NOT NULL,
    section     TEXT NOT NULL,
    status      TEXT NOT NULL,
    action      TEXT,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (dossier_id, section)
);
CREATE TABLE IF NOT EXISTS dossier_index (
    dossier_id      TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    submission_type TEXT,
    cs_be_only      INTEGER NOT NULL DEFAULT 1,
    din             TEXT,
    fee_paid        INTEGER NOT NULL DEFAULT 0,
    sme_granted     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

# columns a caller may patch on a plan item
_ITEM_PATCHABLE = ("assignee", "due_date", "status")


class SqliteDossierRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    # -- content plans ------------------------------------------------------
    def create_plan(self, dossier_id: str, submission_type: str,
                    items: list) -> dict:
        pid = new_id()
        now = utcnow_iso()
        self.db.execute(
            "INSERT INTO content_plans (id, dossier_id, submission_type, "
            "created_at) VALUES (?, ?, ?, ?)",
            (pid, dossier_id, submission_type, now))
        for ord_, item in enumerate(items):
            self.db.execute(
                "INSERT INTO content_plan_items (id, plan_id, dossier_id, ord, "
                "key, title, section, leaf_id, required, status, assignee, "
                "due_date, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), pid, dossier_id, ord_, item["key"], item["title"],
                 item["section"], item.get("leaf_id"),
                 1 if item.get("required", True) else 0,
                 item.get("status", "pending"), item.get("assignee"),
                 item.get("due_date"), now, now))
        return self.get_plan(pid)

    def _assemble(self, plan_row) -> dict:
        items = self.db.fetchall(
            "SELECT * FROM content_plan_items WHERE plan_id = ? "
            "ORDER BY ord", (plan_row["id"],))
        return {"id": plan_row["id"], "dossier_id": plan_row["dossier_id"],
                "submission_type": plan_row["submission_type"],
                "created_at": plan_row["created_at"],
                "items": [self._item(dict(r)) for r in items]}

    @staticmethod
    def _item(row: dict) -> dict:
        row["required"] = bool(row["required"])
        return row

    def get_plan(self, plan_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM content_plans WHERE id = ?", (plan_id,))
        return self._assemble(row) if row else None

    def get_plan_by_dossier(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM content_plans WHERE dossier_id = ? "
            "ORDER BY created_at DESC, id LIMIT 1", (dossier_id,))
        return self._assemble(row) if row else None

    def get_item(self, item_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM content_plan_items WHERE id = ?", (item_id,))
        return self._item(dict(row)) if row else None

    def update_item(self, item_id: str, fields: dict) -> dict | None:
        sets, params = [], []
        for col in _ITEM_PATCHABLE:
            if col in fields:
                sets.append(f"{col} = ?")   # col is a hardcoded literal
                params.append(fields[col])
        if not sets:
            return self.get_item(item_id)
        params.append(utcnow_iso())
        params.append(item_id)
        self.db.execute(
            "UPDATE content_plan_items SET " + ", ".join(sets)
            + ", updated_at = ? WHERE id = ?", tuple(params))
        return self.get_item(item_id)

    # -- product monograph leaves ------------------------------------------
    def upsert_pm_leaf(self, leaf: dict) -> dict:
        self.db.execute(
            "INSERT INTO pm_leaves (dossier_id, lang, leaf_id, title, version, "
            "heading, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(dossier_id, lang) DO UPDATE SET "
            "leaf_id=excluded.leaf_id, title=excluded.title, "
            "version=excluded.version, updated_at=excluded.updated_at",
            (leaf["dossier_id"], leaf["lang"], leaf["leaf_id"], leaf["title"],
             int(leaf.get("version") or 1), leaf["heading"], utcnow_iso()))
        row = self.db.fetchone(
            "SELECT * FROM pm_leaves WHERE dossier_id = ? AND lang = ?",
            (leaf["dossier_id"], leaf["lang"]))
        return dict(row)

    def list_pm_leaves(self, dossier_id: str) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM pm_leaves WHERE dossier_id = ? ORDER BY lang",
            (dossier_id,))
        return [dict(r) for r in rows]

    # -- eCTD assembly model (REQ-107) -------------------------------------
    def get_dossier(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT model FROM dossiers WHERE dossier_id = ?", (dossier_id,))
        return json.loads(row["model"]) if row else None

    def save_dossier(self, model: dict) -> dict:
        self.db.execute(
            "INSERT INTO dossiers (dossier_id, model, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(dossier_id) DO UPDATE SET "
            "model=excluded.model, updated_at=excluded.updated_at",
            (model["dossier_id"], json.dumps(model), utcnow_iso()))
        return model

    # -- submission archive / binder (REQ-110) -----------------------------
    def save_binder(self, dossier_id, sequence, binder) -> dict:
        bid = new_id()
        self.db.execute(
            "INSERT INTO binders (id, dossier_id, sequence, binder, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (bid, dossier_id, sequence, json.dumps(binder), utcnow_iso()))
        return self.get_binder(bid)

    def _binder_row(self, row) -> dict:
        rec = dict(row)
        rec["binder"] = json.loads(rec["binder"])
        return rec

    def get_binder(self, binder_id) -> dict | None:
        row = self.db.fetchone("SELECT * FROM binders WHERE id = ?", (binder_id,))
        return self._binder_row(row) if row else None

    def list_binders(self, dossier_id) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT id, dossier_id, sequence, share_token, created_at FROM "
            "binders WHERE dossier_id = ? ORDER BY created_at", (dossier_id,))
        return [dict(r) for r in rows]

    def set_share_token(self, binder_id, token) -> None:
        self.db.execute("UPDATE binders SET share_token = ? WHERE id = ?",
                        (token, binder_id))

    def get_by_share_token(self, token) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM binders WHERE share_token = ?", (token,))
        return self._binder_row(row) if row else None

    # -- documents (byte store backing) ------------------------------------
    def put_document(self, rec: dict) -> dict:
        self.db.execute(
            "INSERT INTO documents (doc_id, dossier_id, section, filename, "
            "content_type, checksum, size, origin, lang, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rec["doc_id"], rec["dossier_id"], rec["section"], rec["filename"],
             rec["content_type"], rec["checksum"], rec["size"], rec["origin"],
             rec.get("lang"), rec["body"], utcnow_iso()))
        return rec

    def get_document(self, doc_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
        return dict(row) if row else None

    def get_document_meta(self, doc_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT doc_id, dossier_id, section, filename, content_type, "
            "checksum, size, origin, lang, created_at FROM documents "
            "WHERE doc_id = ?", (doc_id,))
        return dict(row) if row else None

    def delete_document(self, doc_id: str) -> None:
        self.db.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))

    # -- per-section state -------------------------------------------------
    def get_section_state(self, dossier_id: str, section: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT data FROM section_state WHERE dossier_id = ? AND section = ?",
            (dossier_id, section))
        return json.loads(row["data"]) if row else None

    def upsert_section_state(self, dossier_id: str, section: str,
                             entry: dict) -> dict:
        self.db.execute(
            "INSERT INTO section_state (dossier_id, section, status, action, "
            "data, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(dossier_id, section) DO UPDATE SET status=excluded.status,"
            " action=excluded.action, data=excluded.data, "
            "updated_at=excluded.updated_at",
            (dossier_id, section, entry.get("status", ""), entry.get("action"),
             json.dumps(entry), utcnow_iso()))
        return entry

    def list_section_state(self, dossier_id: str) -> dict:
        rows = self.db.fetchall(
            "SELECT section, data FROM section_state WHERE dossier_id = ?",
            (dossier_id,))
        return {r["section"]: json.loads(r["data"]) for r in rows}

    # -- dossier index (home catalog) --------------------------------------
    def create_dossier_index(self, rec: dict) -> dict:
        now = utcnow_iso()
        self.db.execute(
            "INSERT INTO dossier_index (dossier_id, title, submission_type, "
            "cs_be_only, din, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(dossier_id) DO UPDATE SET title=excluded.title, "
            "submission_type=excluded.submission_type, "
            "cs_be_only=excluded.cs_be_only, din=excluded.din, "
            "updated_at=excluded.updated_at",
            (rec["dossier_id"], rec["title"], rec.get("submission_type"),
             1 if rec.get("cs_be_only", True) else 0, rec.get("din"), now, now))
        return self.get_dossier_index(rec["dossier_id"])

    def set_fee_status(self, dossier_id: str, fee_paid: bool,
                       sme_granted: bool) -> dict | None:
        self.db.execute(
            "UPDATE dossier_index SET fee_paid = ?, sme_granted = ?, "
            "updated_at = ? WHERE dossier_id = ?",
            (1 if fee_paid else 0, 1 if sme_granted else 0, utcnow_iso(),
             dossier_id))
        return self.get_dossier_index(dossier_id)

    def _index_row(self, row) -> dict:
        rec = dict(row)
        rec["cs_be_only"] = bool(rec["cs_be_only"])
        rec["fee_paid"] = bool(rec.get("fee_paid"))
        rec["sme_granted"] = bool(rec.get("sme_granted"))
        return rec

    def get_dossier_index(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM dossier_index WHERE dossier_id = ?", (dossier_id,))
        return self._index_row(row) if row else None

    def list_dossier_index(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM dossier_index ORDER BY created_at DESC")
        return [self._index_row(r) for r in rows]
