"""Postgres repository adapter (production) — pure-Python ``pg8000`` driver.

Satisfies :class:`app.ports.CollaborationRepository` with the same contract as
the SQLite adapter. Not exercised in the sandbox (no Postgres server); it is
covered by the shared repository contract test run against a real Postgres in CI
/ docker-compose. ``psycopg`` has no Python-3.15 wheel, so ``pg8000`` (pure
Python, paramstyle ``format`` → ``%s`` placeholders) is used.
"""

from __future__ import annotations

import json
import threading

from ands_shared import new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
    author TEXT NOT NULL, body TEXT NOT NULL, parent_id TEXT,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, assignee TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '', due_date TEXT, target_type TEXT,
    target_id TEXT, dossier_id TEXT, status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, recipient TEXT NOT NULL,
    subject TEXT NOT NULL, body TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS email_outbox (
    id TEXT PRIMARY KEY, to_addr TEXT NOT NULL, subject TEXT NOT NULL,
    body TEXT NOT NULL, created_at TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0);
"""


class PostgresCollaborationRepository:
    def __init__(self, dsn: str) -> None:
        import pg8000.dbapi  # lazy: prod-only
        from urllib.parse import urlparse
        u = urlparse(dsn)
        self._conn = pg8000.dbapi.connect(
            user=u.username, password=u.password, host=u.hostname,
            port=u.port or 5432, database=(u.path or "/").lstrip("/"))
        self._lock = threading.Lock()
        self._exec(_SCHEMA, (), script=True)

    def _exec(self, sql: str, params: tuple = (), *, script: bool = False):
        with self._lock:
            cur = self._conn.cursor()
            if script:
                for stmt in filter(str.strip, sql.split(";")):
                    cur.execute(stmt)
            else:
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

    # -- comments -----------------------------------------------------------
    def add_comment(self, comment: dict) -> dict:
        cid, created = new_id(), utcnow_iso()
        self._exec(
            "INSERT INTO comments (id, target_type, target_id, author, body, "
            "parent_id, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (cid, comment["target_type"], comment["target_id"],
             comment["author"], comment["body"], comment.get("parent_id"),
             created))
        return self._one("SELECT * FROM comments WHERE id = %s", (cid,))

    def list_comments(self, target_type: str, target_id: str) -> list[dict]:
        return self._all(
            "SELECT * FROM comments WHERE target_type = %s AND target_id = %s "
            "ORDER BY created_at, id", (target_type, target_id))

    # -- tasks --------------------------------------------------------------
    def add_task(self, task: dict) -> dict:
        tid, now = new_id(), utcnow_iso()
        self._exec(
            "INSERT INTO tasks (id, title, assignee, created_by, due_date, "
            "target_type, target_id, dossier_id, status, created_at, "
            "updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tid, task["title"], task["assignee"], task.get("created_by") or "",
             task.get("due_date"), task.get("target_type"),
             task.get("target_id"), task.get("dossier_id"), task["status"],
             now, now))
        return self.get_task(tid)

    def get_task(self, task_id: str) -> dict | None:
        return self._one("SELECT * FROM tasks WHERE id = %s", (task_id,))

    def list_tasks(self, *, assignee: str = "", dossier_id: str = "",
                   status: str = "") -> list[dict]:
        clauses, params = [], []
        for col, val in (("assignee", assignee), ("dossier_id", dossier_id),
                         ("status", status)):
            if str(val or "").strip():
                clauses.append(f"{col} = %s")  # col is a hardcoded literal
                params.append(str(val).strip())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._all("SELECT * FROM tasks" + where + " ORDER BY created_at, id",
                         tuple(params))

    def set_task_status(self, task_id: str, status: str) -> dict | None:
        self._exec("UPDATE tasks SET status = %s, updated_at = %s WHERE id = %s",
                   (status, utcnow_iso(), task_id))
        return self.get_task(task_id)

    # -- notifications + email outbox --------------------------------------
    def add_notification(self, note: dict) -> dict:
        nid, created = new_id(), utcnow_iso()
        self._exec(
            "INSERT INTO notifications (id, kind, recipient, subject, body, "
            "meta, created_at, read) VALUES (%s,%s,%s,%s,%s,%s,%s,0)",
            (nid, note["kind"], note["recipient"], note["subject"],
             note["body"], json.dumps(note.get("meta") or {}), created))
        row = self._one("SELECT * FROM notifications WHERE id = %s", (nid,))
        row["read"] = bool(row["read"])
        row["meta"] = json.loads(row["meta"])
        return row

    def enqueue_email(self, email: dict) -> dict:
        eid, created = new_id(), utcnow_iso()
        self._exec(
            "INSERT INTO email_outbox (id, to_addr, subject, body, created_at, "
            "sent) VALUES (%s,%s,%s,%s,%s,0)",
            (eid, email["to"], email["subject"], email["body"], created))
        row = self._one("SELECT * FROM email_outbox WHERE id = %s", (eid,))
        row["sent"] = bool(row["sent"])
        return row

    def inbox(self, user: str) -> list[dict]:
        rows = self._all(
            "SELECT * FROM notifications WHERE recipient = %s "
            "ORDER BY created_at DESC, id DESC", (str(user or "").strip(),))
        for r in rows:
            r["read"] = bool(r["read"])
            r["meta"] = json.loads(r["meta"])
        return rows

    def outbox(self) -> list[dict]:
        rows = self._all("SELECT * FROM email_outbox ORDER BY created_at, id")
        for r in rows:
            r["sent"] = bool(r["sent"])
        return rows
