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
