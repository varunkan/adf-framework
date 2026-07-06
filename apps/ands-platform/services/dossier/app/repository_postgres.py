"""Postgres repository adapter (production) — pure-Python ``pg8000``.

Same contract as the SQLite adapter; exercised against a real Postgres in CI /
docker-compose, not in the sandbox.
"""

from __future__ import annotations

import json
import threading

from ands_shared import new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_plans (
    id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL,
    submission_type TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content_plan_items (
    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, dossier_id TEXT NOT NULL,
    ord INTEGER NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL,
    section TEXT NOT NULL, leaf_id TEXT, required INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL, assignee TEXT, due_date TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pm_leaves (
    dossier_id TEXT NOT NULL, lang TEXT NOT NULL, leaf_id TEXT NOT NULL,
    title TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, heading TEXT NOT NULL,
    updated_at TEXT NOT NULL, PRIMARY KEY (dossier_id, lang));
CREATE TABLE IF NOT EXISTS dossiers (
    dossier_id TEXT PRIMARY KEY, model TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS binders (
    id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, sequence TEXT NOT NULL,
    binder TEXT NOT NULL, share_token TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, section TEXT NOT NULL,
    filename TEXT NOT NULL, content_type TEXT NOT NULL, checksum TEXT NOT NULL,
    size BIGINT NOT NULL, origin TEXT NOT NULL, lang TEXT,
    body BYTEA NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS section_state (
    dossier_id TEXT NOT NULL, section TEXT NOT NULL, status TEXT NOT NULL,
    action TEXT, data TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (dossier_id, section));
CREATE TABLE IF NOT EXISTS dossier_index (
    dossier_id TEXT PRIMARY KEY, title TEXT NOT NULL, submission_type TEXT,
    cs_be_only INTEGER NOT NULL DEFAULT 1, din TEXT, company_id TEXT,
    sponsor TEXT, drug_product TEXT, fee_paid INTEGER NOT NULL DEFAULT 0,
    sme_granted INTEGER NOT NULL DEFAULT 0, tenant_id TEXT,
    active_sequence TEXT NOT NULL DEFAULT '0000',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""

_ITEM_PATCHABLE = ("assignee", "due_date", "status")


class PostgresDossierRepository:
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

    def _exec(self, sql: str, params: tuple = ()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    # -- content plans ------------------------------------------------------
    def create_plan(self, dossier_id, submission_type, items) -> dict:
        pid, now = new_id(), utcnow_iso()
        self._exec("INSERT INTO content_plans (id, dossier_id, submission_type, "
                   "created_at) VALUES (%s,%s,%s,%s)",
                   (pid, dossier_id, submission_type, now))
        for ord_, item in enumerate(items):
            self._exec(
                "INSERT INTO content_plan_items (id, plan_id, dossier_id, ord, "
                "key, title, section, leaf_id, required, status, assignee, "
                "due_date, created_at, updated_at) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (new_id(), pid, dossier_id, ord_, item["key"], item["title"],
                 item["section"], item.get("leaf_id"),
                 1 if item.get("required", True) else 0,
                 item.get("status", "pending"), item.get("assignee"),
                 item.get("due_date"), now, now))
        return self.get_plan(pid)

    def _assemble(self, plan: dict) -> dict:
        items = self._all("SELECT * FROM content_plan_items WHERE plan_id = %s "
                          "ORDER BY ord", (plan["id"],))
        for it in items:
            it["required"] = bool(it["required"])
        return {**plan, "items": items}

    def get_plan(self, plan_id) -> dict | None:
        plan = self._one("SELECT * FROM content_plans WHERE id = %s", (plan_id,))
        return self._assemble(plan) if plan else None

    def get_plan_by_dossier(self, dossier_id) -> dict | None:
        plan = self._one("SELECT * FROM content_plans WHERE dossier_id = %s "
                         "ORDER BY created_at DESC, id LIMIT 1", (dossier_id,))
        return self._assemble(plan) if plan else None

    def get_item(self, item_id) -> dict | None:
        it = self._one("SELECT * FROM content_plan_items WHERE id = %s",
                       (item_id,))
        if it:
            it["required"] = bool(it["required"])
        return it

    def update_item(self, item_id, fields) -> dict | None:
        sets, params = [], []
        for col in _ITEM_PATCHABLE:
            if col in fields:
                sets.append(f"{col} = %s")
                params.append(fields[col])
        if not sets:
            return self.get_item(item_id)
        params += [utcnow_iso(), item_id]
        self._exec("UPDATE content_plan_items SET " + ", ".join(sets)
                   + ", updated_at = %s WHERE id = %s", tuple(params))
        return self.get_item(item_id)

    # -- product monograph --------------------------------------------------
    def upsert_pm_leaf(self, leaf) -> dict:
        self._exec(
            "INSERT INTO pm_leaves (dossier_id, lang, leaf_id, title, version, "
            "heading, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (dossier_id, lang) DO UPDATE SET "
            "leaf_id=excluded.leaf_id, title=excluded.title, "
            "version=excluded.version, updated_at=excluded.updated_at",
            (leaf["dossier_id"], leaf["lang"], leaf["leaf_id"], leaf["title"],
             int(leaf.get("version") or 1), leaf["heading"], utcnow_iso()))
        return self._one("SELECT * FROM pm_leaves WHERE dossier_id = %s AND "
                         "lang = %s", (leaf["dossier_id"], leaf["lang"]))

    def list_pm_leaves(self, dossier_id) -> list[dict]:
        return self._all("SELECT * FROM pm_leaves WHERE dossier_id = %s "
                         "ORDER BY lang", (dossier_id,))

    # -- eCTD assembly model (REQ-107) -------------------------------------
    def get_dossier(self, dossier_id) -> dict | None:
        row = self._one("SELECT model FROM dossiers WHERE dossier_id = %s",
                        (dossier_id,))
        return json.loads(row["model"]) if row else None

    def save_dossier(self, model: dict) -> dict:
        self._exec("INSERT INTO dossiers (dossier_id, model, updated_at) "
                   "VALUES (%s,%s,%s) ON CONFLICT (dossier_id) DO UPDATE SET "
                   "model=excluded.model, updated_at=excluded.updated_at",
                   (model["dossier_id"], json.dumps(model), utcnow_iso()))
        return model

    # -- submission archive / binder (REQ-110) -----------------------------
    def save_binder(self, dossier_id, sequence, binder) -> dict:
        bid = new_id()
        self._exec("INSERT INTO binders (id, dossier_id, sequence, binder, "
                   "created_at) VALUES (%s,%s,%s,%s,%s)",
                   (bid, dossier_id, sequence, json.dumps(binder), utcnow_iso()))
        return self.get_binder(bid)

    def get_binder(self, binder_id) -> dict | None:
        row = self._one("SELECT * FROM binders WHERE id = %s", (binder_id,))
        if row:
            row["binder"] = json.loads(row["binder"])
        return row

    def list_binders(self, dossier_id) -> list[dict]:
        return self._all("SELECT id, dossier_id, sequence, share_token, "
                         "created_at FROM binders WHERE dossier_id = %s "
                         "ORDER BY created_at", (dossier_id,))

    def set_share_token(self, binder_id, token) -> None:
        self._exec("UPDATE binders SET share_token = %s WHERE id = %s",
                   (token, binder_id))

    def get_by_share_token(self, token) -> dict | None:
        row = self._one("SELECT * FROM binders WHERE share_token = %s", (token,))
        if row:
            row["binder"] = json.loads(row["binder"])
        return row

    # -- documents (byte store backing) ------------------------------------
    def put_document(self, rec: dict) -> dict:
        self._exec(
            "INSERT INTO documents (doc_id, dossier_id, section, filename, "
            "content_type, checksum, size, origin, lang, body, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (rec["doc_id"], rec["dossier_id"], rec["section"], rec["filename"],
             rec["content_type"], rec["checksum"], rec["size"], rec["origin"],
             rec.get("lang"), rec["body"], utcnow_iso()))
        return rec

    def get_document(self, doc_id: str) -> dict | None:
        row = self._one("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
        if row:
            row["body"] = bytes(row["body"])
        return row

    def get_document_meta(self, doc_id: str) -> dict | None:
        return self._one(
            "SELECT doc_id, dossier_id, section, filename, content_type, "
            "checksum, size, origin, lang, created_at FROM documents "
            "WHERE doc_id = %s", (doc_id,))

    def delete_document(self, doc_id: str) -> None:
        self._exec("DELETE FROM documents WHERE doc_id = %s", (doc_id,))

    # -- per-section state -------------------------------------------------
    def get_section_state(self, dossier_id: str, section: str) -> dict | None:
        row = self._one(
            "SELECT data FROM section_state WHERE dossier_id = %s AND "
            "section = %s", (dossier_id, section))
        return json.loads(row["data"]) if row else None

    def upsert_section_state(self, dossier_id: str, section: str,
                             entry: dict) -> dict:
        self._exec(
            "INSERT INTO section_state (dossier_id, section, status, action, "
            "data, updated_at) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (dossier_id, section) DO UPDATE SET "
            "status=excluded.status, action=excluded.action, "
            "data=excluded.data, updated_at=excluded.updated_at",
            (dossier_id, section, entry.get("status", ""), entry.get("action"),
             json.dumps(entry), utcnow_iso()))
        return entry

    def list_section_state(self, dossier_id: str) -> dict:
        rows = self._all(
            "SELECT section, data FROM section_state WHERE dossier_id = %s",
            (dossier_id,))
        return {r["section"]: json.loads(r["data"]) for r in rows}

    # -- dossier index (home catalog) --------------------------------------
    def create_dossier_index(self, rec: dict) -> dict:
        now = utcnow_iso()
        self._exec(
            "INSERT INTO dossier_index (dossier_id, title, submission_type, "
            "cs_be_only, din, company_id, sponsor, drug_product, tenant_id, "
            "created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (dossier_id) DO UPDATE SET title=excluded.title, "
            "submission_type=excluded.submission_type, "
            "cs_be_only=excluded.cs_be_only, din=excluded.din, "
            # preserve REP identity across upserts that omit it (COALESCE keeps
            # the stored sponsor/company_id when the new rec leaves them NULL)
            "company_id=COALESCE(excluded.company_id, dossier_index.company_id), "
            "sponsor=COALESCE(excluded.sponsor, dossier_index.sponsor), "
            "drug_product=COALESCE(excluded.drug_product, "
            "dossier_index.drug_product), "
            # an upsert never re-homes a dossier to another tenant
            "tenant_id=COALESCE(dossier_index.tenant_id, excluded.tenant_id), "
            "updated_at=excluded.updated_at",
            (rec["dossier_id"], rec["title"], rec.get("submission_type"),
             1 if rec.get("cs_be_only", True) else 0, rec.get("din"),
             rec.get("company_id") or None, rec.get("sponsor") or None,
             rec.get("drug_product") or None,
             rec.get("tenant_id") or None, now, now))
        return self.get_dossier_index(rec["dossier_id"])

    def set_fee_status(self, dossier_id: str, fee_paid: bool,
                       sme_granted: bool) -> dict | None:
        self._exec(
            "UPDATE dossier_index SET fee_paid = %s, sme_granted = %s, "
            "updated_at = %s WHERE dossier_id = %s",
            (1 if fee_paid else 0, 1 if sme_granted else 0, utcnow_iso(),
             dossier_id))
        return self.get_dossier_index(dossier_id)

    def set_active_sequence(self, dossier_id: str, sequence: str) -> None:
        self._exec(
            "UPDATE dossier_index SET active_sequence = %s, updated_at = %s "
            "WHERE dossier_id = %s", (sequence, utcnow_iso(), dossier_id))

    @staticmethod
    def _index_row(rec: dict) -> dict:
        rec["cs_be_only"] = bool(rec["cs_be_only"])
        rec["fee_paid"] = bool(rec.get("fee_paid"))
        rec["sme_granted"] = bool(rec.get("sme_granted"))
        rec["active_sequence"] = rec.get("active_sequence") or "0000"
        return rec

    def get_dossier_index(self, dossier_id: str) -> dict | None:
        row = self._one("SELECT * FROM dossier_index WHERE dossier_id = %s",
                        (dossier_id,))
        return self._index_row(row) if row else None

    def list_dossier_index(self, tenant_id: str | None = None) -> list[dict]:
        if tenant_id:
            # strict: a tenant sees ONLY its own dossiers (unowned/other-tenant
            # dossiers are invisible — the CRO isolation guarantee)
            rows = self._all(
                "SELECT * FROM dossier_index WHERE tenant_id = %s "
                "ORDER BY created_at DESC", (tenant_id,))
        else:
            rows = self._all(
                "SELECT * FROM dossier_index ORDER BY created_at DESC")
        return [self._index_row(r) for r in rows]

    def rename_dossier(self, old_id: str, new_id: str) -> bool:
        """Re-key a dossier (placeholder -> real HC Dossier ID). Rewrites the
        embedded id inside JSON payloads (eCTD model paths, binders, section
        state) as well as the key columns. Caller verified new_id is free."""
        if not self._one(
                "SELECT 1 FROM dossier_index WHERE dossier_id = %s", (old_id,)):
            return False
        # JSON payloads embed the id in eCTD folder paths/hrefs — rewrite them.
        # (No rowid in Postgres; the extra dossier_id predicate keeps the
        # per-row key unambiguous for section_state's composite PK.)
        for table, key_col, payload in (("dossiers", "dossier_id", "model"),
                                        ("binders", "id", "binder"),
                                        ("section_state", "section", "data")):
            rows = self._all(
                f"SELECT {key_col} AS k, {payload} AS p FROM {table} "
                "WHERE dossier_id = %s", (old_id,))
            for r in rows:
                self._exec(
                    f"UPDATE {table} SET {payload} = %s "
                    f"WHERE {key_col} = %s AND dossier_id = %s",
                    (str(r["p"]).replace(old_id, new_id), r["k"], old_id))
        for table in ("dossier_index", "dossiers", "section_state", "documents",
                      "binders", "pm_leaves", "content_plans",
                      "content_plan_items"):
            self._exec(
                f"UPDATE {table} SET dossier_id = %s WHERE dossier_id = %s",
                (new_id, old_id))
        return True

    def delete_dossier(self, dossier_id: str) -> bool:
        existed = bool(
            self._one("SELECT 1 FROM dossier_index WHERE dossier_id = %s",
                      (dossier_id,))
            or self._one("SELECT 1 FROM dossiers WHERE dossier_id = %s",
                         (dossier_id,)))
        for table in ("dossier_index", "dossiers", "section_state", "documents",
                      "binders", "pm_leaves", "content_plans"):
            self._exec(f"DELETE FROM {table} WHERE dossier_id = %s",
                       (dossier_id,))
        # plan items key off plan_id, not dossier_id — clear orphans
        self._exec(
            "DELETE FROM content_plan_items WHERE plan_id NOT IN "
            "(SELECT id FROM content_plans)")
        return existed
