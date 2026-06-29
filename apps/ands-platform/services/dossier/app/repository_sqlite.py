"""SQLite repository adapter for the dossier service (dev/test)."""

from __future__ import annotations

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
