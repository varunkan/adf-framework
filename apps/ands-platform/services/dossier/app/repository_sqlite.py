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
    -- WS3 immutable internal identity: assigned once at creation and NEVER
    -- changed by rename/archive/restore. The durable audit ledger keys off THIS
    -- (not the human dossier_id, which is reusable after a rename-away), so a
    -- new dossier reusing a freed dossier_id gets a fresh uid and inherits no
    -- prior dossier's events. The human dossier_id is denormalized context.
    uid             TEXT,
    title           TEXT NOT NULL,
    submission_type TEXT,
    cs_be_only      INTEGER NOT NULL DEFAULT 1,
    din             TEXT,
    company_id      TEXT,
    sponsor         TEXT,
    drug_product    TEXT,
    -- WS6 portfolio: the accountable PM/owner for this dossier (one value per
    -- dossier; distinct from the many per-plan-item assignees and the sponsor)
    owner           TEXT,
    fee_paid        INTEGER NOT NULL DEFAULT 0,
    sme_granted     INTEGER NOT NULL DEFAULT 0,
    tenant_id       TEXT,
    active_sequence TEXT NOT NULL DEFAULT '0000',
    -- WS3 recoverable delete: a soft-archive stamp (who/when/why). NULL
    -- archived_at == live; a value == archived (excluded from the working
    -- catalog, still restorable). The dossier's bytes are NEVER purged.
    archived_at     TEXT,
    archived_by     TEXT,
    archive_reason  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
-- WS3 Part-11 DURABLE AUDIT: a service-local, append-only ledger written
-- SYNCHRONOUSLY in the same SQLite DB as the mutation. This — NOT the
-- best-effort governance forward — is the authoritative durable record of a
-- destructive rename/archive/restore. It survives a dead governance service.
-- Rows are never updated or deleted; ``seq`` is a monotone insert order.
CREATE TABLE IF NOT EXISTS dossier_events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    -- the IMMUTABLE dossier uid this event belongs to (keying identity). A
    -- rename changes dossier_id but not uid, so the ledger stays attached to
    -- the same real dossier; a reused dossier_id (fresh uid) inherits nothing.
    uid         TEXT,
    -- denormalized human dossier_id AT THE TIME of the event (context only —
    -- NOT the key; a reused id must not surface a prior dossier's rows).
    dossier_id  TEXT NOT NULL,
    tenant_id   TEXT,
    actor       TEXT,
    reason      TEXT,
    data        TEXT NOT NULL,
    timestamp   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dossier_events_did
    ON dossier_events (dossier_id);
CREATE INDEX IF NOT EXISTS ix_dossier_events_uid
    ON dossier_events (uid);
-- Re-key chain: a rename OVERWRITES dossier_id across every table, so history
-- recorded under the OLD id would be orphaned. This maps new_id -> old_id so a
-- history read for the current id can walk back and still resolve prior events.
CREATE TABLE IF NOT EXISTS dossier_rename_chain (
    new_id      TEXT PRIMARY KEY,
    old_id      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""

# columns a caller may patch on a plan item
_ITEM_PATCHABLE = ("assignee", "due_date", "status")


class SqliteDossierRepository:
    _MIGRATIONS = (
        # pre-tenancy databases lack the column; ALTER is a no-op error then
        "ALTER TABLE dossier_index ADD COLUMN tenant_id TEXT",
        # pre-lifecycle databases lack the working-sequence pointer
        "ALTER TABLE dossier_index ADD COLUMN active_sequence TEXT "
        "NOT NULL DEFAULT '0000'",
        # REP regulatory-transaction identity: sponsor company id + name
        # (distinct from the product title) — captured at dossier creation
        "ALTER TABLE dossier_index ADD COLUMN company_id TEXT",
        "ALTER TABLE dossier_index ADD COLUMN sponsor TEXT",
        "ALTER TABLE dossier_index ADD COLUMN drug_product TEXT",
        # WS6 portfolio: per-dossier accountable owner (PM/assignee)
        "ALTER TABLE dossier_index ADD COLUMN owner TEXT",
        # WS3 recoverable delete: soft-archive stamp (who/when/why)
        "ALTER TABLE dossier_index ADD COLUMN archived_at TEXT",
        "ALTER TABLE dossier_index ADD COLUMN archived_by TEXT",
        "ALTER TABLE dossier_index ADD COLUMN archive_reason TEXT",
        # WS3 immutable internal identity for the uid-keyed audit ledger
        "ALTER TABLE dossier_index ADD COLUMN uid TEXT",
        # WS3 uid-keyed ledger: pre-existing events rows lack the uid column
        "ALTER TABLE dossier_events ADD COLUMN uid TEXT",
    )

    # DDL that must run on pre-existing DBs too (the durable audit ledger +
    # rename chain). executescript in __init__ creates them on fresh DBs; these
    # cover a DB created before this feature. IF NOT EXISTS makes them no-ops.
    _POST_DDL = (
        "CREATE TABLE IF NOT EXISTS dossier_events ("
        " seq INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,"
        " uid TEXT, dossier_id TEXT NOT NULL, tenant_id TEXT, actor TEXT,"
        " reason TEXT, data TEXT NOT NULL, timestamp TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS ix_dossier_events_did"
        " ON dossier_events (dossier_id)",
        "CREATE INDEX IF NOT EXISTS ix_dossier_events_uid"
        " ON dossier_events (uid)",
        "CREATE TABLE IF NOT EXISTS dossier_rename_chain ("
        " new_id TEXT PRIMARY KEY, old_id TEXT NOT NULL,"
        " created_at TEXT NOT NULL)",
    )

    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)
        for mig in self._MIGRATIONS:
            try:
                self.db.execute(mig)
            except Exception:
                pass   # column already exists (fresh schema or re-run)
        for ddl in self._POST_DDL:
            try:
                self.db.execute(ddl)
            except Exception:
                pass   # already present
        self._backfill_uids()

    def _backfill_uids(self) -> None:
        """Idempotently give every pre-existing DOSSIER an immutable uid (rows
        written before this feature). New rows get one at insert.

        Pre-feature EVENT rows are deliberately NOT rewritten — the ledger is
        append-only (never UPDATE/DELETE dossier_events). Those legacy rows carry
        no uid; ``list_events`` resolves them by their denormalized dossier_id as
        a read-time fallback. New events always carry a uid, so the id-reuse
        leak is closed for everything written under this feature."""
        try:
            rows = self.db.fetchall(
                "SELECT dossier_id FROM dossier_index "
                "WHERE uid IS NULL OR uid = ''")
        except Exception:
            return
        for r in rows:
            self.db.execute(
                "UPDATE dossier_index SET uid = ? WHERE dossier_id = ? "
                "AND (uid IS NULL OR uid = '')", (new_id(), r["dossier_id"]))

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
        # Mint an immutable uid for a genuine INSERT. On CONFLICT (a re-create /
        # upsert of an existing dossier) the stored uid is PRESERVED (COALESCE),
        # so a dossier's audit identity is stable for its whole life — a rename
        # never changes it, and a re-create of the same live id keeps the same
        # ledger. (A dossier_id freed by a rename-away and later re-created gets
        # here as an INSERT — a fresh uid — because the old row now carries the
        # new id, so this row does not exist yet.)
        uid = new_id()
        self.db.execute(
            "INSERT INTO dossier_index (dossier_id, uid, title, submission_type, "
            "cs_be_only, din, company_id, sponsor, drug_product, owner, "
            "tenant_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(dossier_id) DO UPDATE SET title=excluded.title, "
            # a re-create keeps the original uid — never re-key the ledger
            "uid=COALESCE(dossier_index.uid, excluded.uid), "
            "submission_type=excluded.submission_type, "
            "cs_be_only=excluded.cs_be_only, din=excluded.din, "
            # preserve REP identity across upserts that omit it (COALESCE keeps
            # the stored sponsor/company_id when the new rec leaves them NULL)
            "company_id=COALESCE(excluded.company_id, dossier_index.company_id), "
            "sponsor=COALESCE(excluded.sponsor, dossier_index.sponsor), "
            "drug_product=COALESCE(excluded.drug_product, "
            "dossier_index.drug_product), "
            # WS6: preserve the owner across upserts that omit it (COALESCE)
            "owner=COALESCE(excluded.owner, dossier_index.owner), "
            # an upsert never re-homes a dossier to another tenant
            "tenant_id=COALESCE(dossier_index.tenant_id, excluded.tenant_id), "
            "updated_at=excluded.updated_at",
            (rec["dossier_id"], uid, rec["title"], rec.get("submission_type"),
             1 if rec.get("cs_be_only", True) else 0, rec.get("din"),
             rec.get("company_id") or None, rec.get("sponsor") or None,
             rec.get("drug_product") or None, rec.get("owner") or None,
             rec.get("tenant_id") or None, now, now))
        return self.get_dossier_index(rec["dossier_id"])

    def _uid_for(self, dossier_id: str) -> str | None:
        """The immutable uid of the dossier CURRENTLY holding this dossier_id,
        or None if absent. This is the audit-ledger key — resolved from the live
        index row, so a reused human id maps only to ITS OWN uid."""
        row = self.db.fetchone(
            "SELECT uid FROM dossier_index WHERE dossier_id = ?", (dossier_id,))
        return (row["uid"] if row else None) or None

    def set_fee_status(self, dossier_id: str, fee_paid: bool,
                       sme_granted: bool) -> dict | None:
        self.db.execute(
            "UPDATE dossier_index SET fee_paid = ?, sme_granted = ?, "
            "updated_at = ? WHERE dossier_id = ?",
            (1 if fee_paid else 0, 1 if sme_granted else 0, utcnow_iso(),
             dossier_id))
        return self.get_dossier_index(dossier_id)

    def set_active_sequence(self, dossier_id: str, sequence: str) -> None:
        self.db.execute(
            "UPDATE dossier_index SET active_sequence = ?, updated_at = ? "
            "WHERE dossier_id = ?", (sequence, utcnow_iso(), dossier_id))

    def _index_row(self, row) -> dict:
        rec = dict(row)
        rec["cs_be_only"] = bool(rec["cs_be_only"])
        rec["fee_paid"] = bool(rec.get("fee_paid"))
        rec["sme_granted"] = bool(rec.get("sme_granted"))
        rec["active_sequence"] = rec.get("active_sequence") or "0000"
        rec["archived"] = bool(rec.get("archived_at"))
        rec["uid"] = rec.get("uid") or ""
        return rec

    def get_dossier_index(self, dossier_id: str) -> dict | None:
        # resolves archived rows too — restore + content access need it; the
        # working-catalog exclusion lives in list_dossier_index alone.
        row = self.db.fetchone(
            "SELECT * FROM dossier_index WHERE dossier_id = ?", (dossier_id,))
        return self._index_row(row) if row else None

    def list_dossier_index(self, tenant_id: str | None = None) -> list[dict]:
        # WS3: the working catalog excludes soft-archived dossiers.
        if tenant_id:
            # strict: a tenant sees ONLY its own dossiers (unowned/other-tenant
            # dossiers are invisible — the CRO isolation guarantee)
            rows = self.db.fetchall(
                "SELECT * FROM dossier_index WHERE tenant_id = ? "
                "AND archived_at IS NULL ORDER BY created_at DESC", (tenant_id,))
        else:
            rows = self.db.fetchall(
                "SELECT * FROM dossier_index WHERE archived_at IS NULL "
                "ORDER BY created_at DESC")
        return [self._index_row(r) for r in rows]

    def list_archived_index(self, tenant_id: str | None = None) -> list[dict]:
        """The 'trash' view — soft-archived dossiers, restorable, newest-first
        by archive time. Same tenant partition as the working catalog."""
        if tenant_id:
            rows = self.db.fetchall(
                "SELECT * FROM dossier_index WHERE tenant_id = ? "
                "AND archived_at IS NOT NULL ORDER BY archived_at DESC",
                (tenant_id,))
        else:
            rows = self.db.fetchall(
                "SELECT * FROM dossier_index WHERE archived_at IS NOT NULL "
                "ORDER BY archived_at DESC")
        return [self._index_row(r) for r in rows]

    def archive_dossier(self, dossier_id: str, *, actor: str = "",
                        reason: str = "") -> bool:
        """Soft-delete: stamp who/when/why. Reversible — nothing is purged.
        Returns False when the dossier is absent or already archived."""
        row = self.db.fetchone(
            "SELECT archived_at FROM dossier_index WHERE dossier_id = ?",
            (dossier_id,))
        if not row or row["archived_at"]:
            return False
        self.db.execute(
            "UPDATE dossier_index SET archived_at = ?, archived_by = ?, "
            "archive_reason = ?, updated_at = ? WHERE dossier_id = ?",
            (utcnow_iso(), actor or None, reason or None, utcnow_iso(),
             dossier_id))
        return True

    def restore_dossier(self, dossier_id: str) -> bool:
        """Undo a soft-delete: clear the archive stamp. Returns False when the
        dossier is absent or not currently archived."""
        row = self.db.fetchone(
            "SELECT archived_at FROM dossier_index WHERE dossier_id = ?",
            (dossier_id,))
        if not row or not row["archived_at"]:
            return False
        self.db.execute(
            "UPDATE dossier_index SET archived_at = NULL, archived_by = NULL, "
            "archive_reason = NULL, updated_at = ? WHERE dossier_id = ?",
            (utcnow_iso(), dossier_id))
        return True

    # -- WS3 DURABLE append-only audit ledger ------------------------------
    def append_event(self, event_type: str, dossier_id: str, *,
                     actor: str = "", reason: str = "",
                     tenant_id: str = "", data: dict | None = None) -> dict:
        """Append one immutable audit event, SYNCHRONOUSLY, in the SAME DB as
        the mutation. This is the authoritative Part-11 record — it cannot be
        lost when the governance forward is down. Rows are never mutated.

        The event is keyed on the dossier's IMMUTABLE uid (resolved from the
        current index row), with the human dossier_id kept only as denormalized
        context. That is what stops a dossier_id reused after a rename-away from
        inheriting a prior dossier's ledger. Call this INSIDE a
        ``db.transaction()`` alongside the state mutation so the two commit
        atomically (no mutation without a record, no phantom record)."""
        ts = utcnow_iso()
        uid = self._uid_for(str(dossier_id or "").strip())
        cur = self.db.execute(
            "INSERT INTO dossier_events (event_type, uid, dossier_id, "
            "tenant_id, actor, reason, data, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(event_type or ""), uid, str(dossier_id or ""),
             str(tenant_id or "") or None, str(actor or "") or None,
             str(reason or "") or None, json.dumps(data or {}), ts))
        return {"seq": cur.lastrowid, "event_type": event_type, "uid": uid,
                "dossier_id": dossier_id, "actor": actor, "reason": reason,
                "tenant_id": tenant_id, "data": dict(data or {}),
                "timestamp": ts}

    def list_events(self, dossier_id: str) -> list[dict]:
        """The durable ledger for a dossier, newest-first, resolved by the
        dossier's IMMUTABLE uid. A rename changes dossier_id but not uid, so all
        of a dossier's events (incl. those recorded under a prior id) surface;
        a NEW dossier reusing a freed id has a fresh uid and inherits none."""
        did = str(dossier_id or "").strip()
        uid = self._uid_for(did)
        if not uid:
            return []
        # Resolved STRICTLY by the immutable uid — never by the reusable
        # dossier_id. This ledger has always been uid-keyed (the table is
        # introduced with the uid column), so there are no NULL-uid rows to
        # fall back to; matching on dossier_id would be a cross-dossier leak
        # vector (a reused id inheriting a prior dossier's events), so we don't.
        rows = self.db.fetchall(
            "SELECT * FROM dossier_events WHERE uid = ? ORDER BY seq DESC",
            (uid,))
        out = []
        for r in rows:
            rec = dict(r)
            rec["data"] = json.loads(rec["data"]) if rec.get("data") else {}
            rec["actor"] = rec.get("actor") or ""
            rec["reason"] = rec.get("reason") or ""
            rec["tenant_id"] = rec.get("tenant_id") or ""
            out.append(rec)
        return out

    def record_rename_chain(self, old_id: str, new_id: str) -> None:
        # Retained for API compatibility. The uid-keyed ledger no longer needs
        # an id-lineage walk to resolve history (the uid is stable across a
        # rename), so this is a harmless denormalized breadcrumb only.
        self.db.execute(
            "INSERT OR REPLACE INTO dossier_rename_chain (new_id, old_id, "
            "created_at) VALUES (?, ?, ?)", (new_id, old_id, utcnow_iso()))

    # -- WS3 ATOMIC mutation+ledger operations -----------------------------
    # Each pairs the state mutation with its durable audit write in ONE
    # transaction: either both commit or neither. This is what makes "no
    # mutation without a record" and "no phantom record" hold SIMULTANEOUSLY —
    # a failed ledger write rolls the mutation back; a raced mutation (returns
    # no-op) rolls the ledger event back.

    def archive_with_event(self, dossier_id: str, *, actor: str, reason: str,
                           event_type: str, tenant_id: str,
                           data: dict) -> dict | None:
        """Soft-archive AND record the durable audit event atomically. Returns
        the appended event dict, or None if the dossier is absent/already
        archived (nothing committed)."""
        with self.db.transaction():
            if not self.archive_dossier(dossier_id, actor=actor, reason=reason):
                return None   # rolls back — no phantom event
            return self.append_event(event_type, dossier_id, actor=actor,
                                     reason=reason, tenant_id=tenant_id,
                                     data=data)

    def restore_with_event(self, dossier_id: str, *, actor: str, reason: str,
                           event_type: str, tenant_id: str,
                           data: dict) -> dict | None:
        """Restore AND record the durable audit event atomically. Returns the
        appended event, or None if not currently archived (nothing committed)."""
        with self.db.transaction():
            if not self.restore_dossier(dossier_id):
                return None
            return self.append_event(event_type, dossier_id, actor=actor,
                                     reason=reason, tenant_id=tenant_id,
                                     data=data)

    def rename_with_event(self, old_id: str, new_id: str, *, actor: str,
                          reason: str, event_type: str, tenant_id: str,
                          data: dict) -> dict | None:
        """Re-key AND record the durable audit event + rename-chain atomically.
        The uid is stable across the re-key, so the event (appended under the
        NEW id post-rekey) lands on the SAME uid as the dossier's prior events.
        Returns the appended event, or None if the re-key was a no-op (nothing
        committed — no orphan chain, no phantom 'renamed' event)."""
        with self.db.transaction():
            if not self.rename_dossier(old_id, new_id):
                return None
            ev = self.append_event(event_type, new_id, actor=actor,
                                   reason=reason, tenant_id=tenant_id,
                                   data=data)
            self.record_rename_chain(old_id, new_id)
            return ev

    def rename_dossier(self, old_id: str, new_id: str) -> bool:
        """Re-key a dossier (placeholder -> real HC Dossier ID). Rewrites the
        embedded id inside JSON payloads (eCTD model paths, binders, section
        state) as well as the key columns. Caller verified new_id is free."""
        if not self.db.fetchone(
                "SELECT 1 FROM dossier_index WHERE dossier_id = ?", (old_id,)):
            return False
        # JSON payloads embed the id in eCTD folder paths/hrefs — rewrite them.
        for table, key_col, payload in (("dossiers", "dossier_id", "model"),
                                        ("binders", "id", "binder"),
                                        ("section_state", "rowid", "data")):
            rows = self.db.fetchall(
                f"SELECT {key_col} AS k, {payload} AS p FROM {table} "
                "WHERE dossier_id = ?", (old_id,))
            for r in rows:
                self.db.execute(
                    f"UPDATE {table} SET {payload} = ? WHERE {key_col} = ?",
                    (str(r["p"]).replace(old_id, new_id), r["k"]))
        for table in ("dossier_index", "dossiers", "section_state", "documents",
                      "binders", "pm_leaves", "content_plans",
                      "content_plan_items"):
            self.db.execute(
                f"UPDATE {table} SET dossier_id = ? WHERE dossier_id = ?",
                (new_id, old_id))
        return True

    def delete_dossier(self, dossier_id: str) -> bool:
        existed = bool(
            self.db.fetchone("SELECT 1 FROM dossier_index WHERE dossier_id = ?",
                             (dossier_id,))
            or self.db.fetchone("SELECT 1 FROM dossiers WHERE dossier_id = ?",
                                (dossier_id,)))
        for table in ("dossier_index", "dossiers", "section_state", "documents",
                      "binders", "pm_leaves", "content_plans"):
            self.db.execute(f"DELETE FROM {table} WHERE dossier_id = ?",
                            (dossier_id,))
        # plan items key off plan_id, not dossier_id — clear orphans
        self.db.execute(
            "DELETE FROM content_plan_items WHERE plan_id NOT IN "
            "(SELECT id FROM content_plans)")
        return existed
