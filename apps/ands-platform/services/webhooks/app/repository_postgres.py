"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import json
import threading

from ands_shared import new_id, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY, url TEXT NOT NULL, event_types TEXT NOT NULL,
    tenant_id TEXT, secret TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL, event_type TEXT NOT NULL,
    url TEXT NOT NULL, payload TEXT NOT NULL, signature TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class PostgresWebhookRepository:
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

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql, params=()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    @staticmethod
    def _sub(rec):
        rec["event_types"] = json.loads(rec["event_types"])
        return rec

    def add_subscription(self, sub: dict) -> dict:
        sid = new_id()
        self._exec("INSERT INTO subscriptions (id, url, event_types, tenant_id, "
                   "secret, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                   (sid, sub["url"], json.dumps(sub["event_types"]),
                    sub.get("tenant_id"), sub["secret"], utcnow_iso()))
        return self.get_subscription(sid)

    def get_subscription(self, sub_id):
        rows = self._all("SELECT * FROM subscriptions WHERE id = %s", (sub_id,))
        return self._sub(rows[0]) if rows else None

    def list_subscriptions(self, *, tenant_id=""):
        if str(tenant_id or "").strip():
            rows = self._all("SELECT * FROM subscriptions WHERE tenant_id = %s "
                             "ORDER BY created_at", (tenant_id,))
        else:
            rows = self._all("SELECT * FROM subscriptions ORDER BY created_at")
        return [self._sub(r) for r in rows]

    def all_subscriptions(self):
        return self.list_subscriptions()

    def delete_subscription(self, sub_id) -> bool:
        return self._exec("DELETE FROM subscriptions WHERE id = %s",
                          (sub_id,)).rowcount > 0

    def enqueue_delivery(self, delivery: dict) -> dict:
        did = new_id()
        self._exec("INSERT INTO deliveries (id, subscription_id, event_type, "
                   "url, payload, signature, status, created_at) "
                   "VALUES (%s,%s,%s,%s,%s,%s,'pending',%s)",
                   (did, delivery["subscription_id"], delivery["event_type"],
                    delivery["url"], delivery["payload"], delivery["signature"],
                    utcnow_iso()))
        return self._all("SELECT * FROM deliveries WHERE id = %s", (did,))[0]

    def list_deliveries(self, *, subscription_id=""):
        if str(subscription_id or "").strip():
            return self._all("SELECT * FROM deliveries WHERE subscription_id = "
                             "%s ORDER BY created_at", (subscription_id,))
        return self._all("SELECT * FROM deliveries ORDER BY created_at")
