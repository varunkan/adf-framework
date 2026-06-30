"""SQLite repository adapter for the webhooks service (dev/test)."""

from __future__ import annotations

import json

from ands_shared import SqliteDb, new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id          TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    event_types TEXT NOT NULL,
    tenant_id   TEXT,
    secret      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    id              TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    url             TEXT NOT NULL,
    payload         TEXT NOT NULL,
    signature       TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""


class SqliteWebhookRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)

    @staticmethod
    def _sub(row) -> dict:
        rec = dict(row)
        rec["event_types"] = json.loads(rec["event_types"])
        return rec

    def add_subscription(self, sub: dict) -> dict:
        sid = new_id()
        self.db.execute(
            "INSERT INTO subscriptions (id, url, event_types, tenant_id, "
            "secret, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, sub["url"], json.dumps(sub["event_types"]),
             sub.get("tenant_id"), sub["secret"], utcnow_iso()))
        return self.get_subscription(sid)

    def get_subscription(self, sub_id: str) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM subscriptions WHERE id = ?", (sub_id,))
        return self._sub(row) if row else None

    def list_subscriptions(self, *, tenant_id: str = "") -> list[dict]:
        if str(tenant_id or "").strip():
            rows = self.db.fetchall(
                "SELECT * FROM subscriptions WHERE tenant_id = ? "
                "ORDER BY created_at", (tenant_id,))
        else:
            rows = self.db.fetchall(
                "SELECT * FROM subscriptions ORDER BY created_at")
        return [self._sub(r) for r in rows]

    def all_subscriptions(self) -> list[dict]:
        return self.list_subscriptions()

    def delete_subscription(self, sub_id: str) -> bool:
        cur = self.db.execute(
            "DELETE FROM subscriptions WHERE id = ?", (sub_id,))
        return cur.rowcount > 0

    def enqueue_delivery(self, delivery: dict) -> dict:
        did = new_id()
        self.db.execute(
            "INSERT INTO deliveries (id, subscription_id, event_type, url, "
            "payload, signature, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (did, delivery["subscription_id"], delivery["event_type"],
             delivery["url"], delivery["payload"], delivery["signature"],
             utcnow_iso()))
        return dict(self.db.fetchone(
            "SELECT * FROM deliveries WHERE id = ?", (did,)))

    def list_deliveries(self, *, subscription_id: str = "") -> list[dict]:
        if str(subscription_id or "").strip():
            rows = self.db.fetchall(
                "SELECT * FROM deliveries WHERE subscription_id = ? "
                "ORDER BY created_at", (subscription_id,))
        else:
            rows = self.db.fetchall(
                "SELECT * FROM deliveries ORDER BY created_at")
        return [dict(r) for r in rows]
