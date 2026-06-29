"""SQLite repository adapter — the dev/test persistence (runs in-sandbox).

Satisfies :class:`app.ports.CollaborationRepository`. Production uses
``repository_postgres`` instead; both share the same contract test. Built on the
shared, thread-safe :class:`ands_shared.SqliteDb`.
"""

from __future__ import annotations

import json

from ands_shared import SqliteDb, new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id          TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    author      TEXT NOT NULL,
    body        TEXT NOT NULL,
    parent_id   TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    assignee    TEXT NOT NULL,
    created_by  TEXT NOT NULL DEFAULT '',
    due_date    TEXT,
    target_type TEXT,
    target_id   TEXT,
    dossier_id  TEXT,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    recipient   TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    read        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS email_outbox (
    id          TEXT PRIMARY KEY,
    to_addr     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0
);
"""


class SqliteCollaborationRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    # -- comments -----------------------------------------------------------
    def add_comment(self, comment: dict) -> dict:
        cid = new_id()
        created = utcnow_iso()
        self.db.execute(
            "INSERT INTO comments (id, target_type, target_id, author, body, "
            "parent_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, comment["target_type"], comment["target_id"],
             comment["author"], comment["body"], comment.get("parent_id"),
             created))
        return self._comment(cid)

    def _comment(self, cid: str) -> dict:
        return dict(self.db.fetchone(
            "SELECT * FROM comments WHERE id = ?", (cid,)))

    def list_comments(self, target_type: str, target_id: str) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM comments WHERE target_type = ? AND target_id = ? "
            "ORDER BY created_at, id", (target_type, target_id))
        return [dict(r) for r in rows]

    # -- tasks --------------------------------------------------------------
    def add_task(self, task: dict) -> dict:
        tid = new_id()
        now = utcnow_iso()
        self.db.execute(
            "INSERT INTO tasks (id, title, assignee, created_by, due_date, "
            "target_type, target_id, dossier_id, status, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, task["title"], task["assignee"], task.get("created_by") or "",
             task.get("due_date"), task.get("target_type"),
             task.get("target_id"), task.get("dossier_id"), task["status"],
             now, now))
        return self.get_task(tid)

    def get_task(self, task_id: str) -> dict | None:
        row = self.db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return dict(row) if row else None

    def list_tasks(self, *, assignee: str = "", dossier_id: str = "",
                   status: str = "") -> list[dict]:
        clauses, params = [], []
        for col, val in (("assignee", assignee), ("dossier_id", dossier_id),
                         ("status", status)):
            if str(val or "").strip():
                clauses.append(f"{col} = ?")  # col is a hardcoded literal
                params.append(str(val).strip())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.fetchall(
            "SELECT * FROM tasks" + where + " ORDER BY created_at, id",
            tuple(params))
        return [dict(r) for r in rows]

    def set_task_status(self, task_id: str, status: str) -> dict | None:
        self.db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, utcnow_iso(), task_id))
        return self.get_task(task_id)

    # -- notifications + email outbox --------------------------------------
    def add_notification(self, note: dict) -> dict:
        nid = new_id()
        created = utcnow_iso()
        self.db.execute(
            "INSERT INTO notifications (id, kind, recipient, subject, body, "
            "meta, created_at, read) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (nid, note["kind"], note["recipient"], note["subject"],
             note["body"], json.dumps(note.get("meta") or {}), created))
        return self._notification(nid)

    def _notification(self, nid: str) -> dict:
        row = dict(self.db.fetchone(
            "SELECT * FROM notifications WHERE id = ?", (nid,)))
        row["read"] = bool(row["read"])
        row["meta"] = json.loads(row["meta"])
        return row

    def enqueue_email(self, email: dict) -> dict:
        eid = new_id()
        created = utcnow_iso()
        self.db.execute(
            "INSERT INTO email_outbox (id, to_addr, subject, body, created_at, "
            "sent) VALUES (?, ?, ?, ?, ?, 0)",
            (eid, email["to"], email["subject"], email["body"], created))
        row = dict(self.db.fetchone(
            "SELECT * FROM email_outbox WHERE id = ?", (eid,)))
        row["sent"] = bool(row["sent"])
        return row

    def inbox(self, user: str) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM notifications WHERE recipient = ? "
            "ORDER BY created_at DESC, id DESC", (str(user or "").strip(),))
        out = []
        for r in rows:
            rec = dict(r)
            rec["read"] = bool(rec["read"])
            rec["meta"] = json.loads(rec["meta"])
            out.append(rec)
        return out

    def outbox(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM email_outbox ORDER BY created_at, id")
        out = []
        for r in rows:
            rec = dict(r)
            rec["sent"] = bool(rec["sent"])
            out.append(rec)
        return out
