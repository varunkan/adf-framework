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
CREATE TABLE IF NOT EXISTS noa_allegations (
    id         TEXT PRIMARY KEY,
    dossier_id TEXT NOT NULL,
    record     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SqliteLifecycleRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    def save(self, state: dict) -> dict:
        self.db.execute(
            "INSERT INTO lifecycles (dossier_id, state, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(dossier_id) DO UPDATE SET "
            "state=excluded.state, updated_at=excluded.updated_at",
            (state["dossier_id"], json.dumps(state), utcnow_iso()))
        return state

    def get(self, dossier_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT state FROM lifecycles WHERE dossier_id = ?", (dossier_id,))
        return json.loads(row["state"]) if row else None

    def list(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT state FROM lifecycles ORDER BY updated_at")
        return [json.loads(r["state"]) for r in rows]

    # -- HC correspondence (REQ-112) ---------------------------------------
    def add_correspondence(self, record: dict) -> dict:
        cid = new_id()
        self.db.execute(
            "INSERT INTO correspondence (id, dossier_id, kind, kind_label, "
            "subject, body, direction, received_at, reference, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, record["dossier_id"], record["kind"], record["kind_label"],
             record["subject"], record.get("body"), record["direction"],
             record.get("received_at"), record.get("reference"), utcnow_iso()))
        return dict(self.db.fetchone(
            "SELECT * FROM correspondence WHERE id = ?", (cid,)))

    def list_correspondence(self, dossier_id: str, kind: str = "") -> list[dict]:
        if str(kind or "").strip():
            rows = self.db.fetchall(
                "SELECT * FROM correspondence WHERE dossier_id = ? AND kind = ? "
                "ORDER BY created_at", (dossier_id, kind))
        else:
            rows = self.db.fetchall(
                "SELECT * FROM correspondence WHERE dossier_id = ? "
                "ORDER BY created_at", (dossier_id,))
        return [dict(r) for r in rows]

    # -- Form V / NOA register (PM(NOC) Regulations) -------------------------
    def add_noa(self, record: dict) -> dict:
        record = dict(record, id=new_id())
        now = utcnow_iso()
        self.db.execute(
            "INSERT INTO noa_allegations (id, dossier_id, record, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?)",
            (record["id"], record["dossier_id"], json.dumps(record), now, now))
        return record

    def get_noa(self, noa_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT record FROM noa_allegations WHERE id = ?", (noa_id,))
        return json.loads(row["record"]) if row else None

    def save_noa(self, record: dict) -> dict:
        self.db.execute(
            "UPDATE noa_allegations SET record = ?, updated_at = ? "
            "WHERE id = ?", (json.dumps(record), utcnow_iso(), record["id"]))
        return record

    def list_noa(self, dossier_id: str) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT record FROM noa_allegations WHERE dossier_id = ? "
            "ORDER BY created_at", (dossier_id,))
        return [json.loads(r["record"]) for r in rows]
