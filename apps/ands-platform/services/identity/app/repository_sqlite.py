"""SQLite repository adapter for the identity service (dev/test).

Holds the control-plane tables: users, sessions, tenants, plans, overrides.
Seeds the built-in all-features default plan on init.
"""

from __future__ import annotations

import json

from ands_shared import SqliteDb, new_id, utcnow_iso

from . import entitlements

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, email TEXT NOT NULL,
    pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL, role TEXT NOT NULL,
    name TEXT, created_at TEXT NOT NULL,
    mfa_secret TEXT, mfa_enabled INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tenant_id, email));
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
    role TEXT NOT NULL, email TEXT NOT NULL, created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, plan_id TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, features TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS overrides (
    tenant_id TEXT NOT NULL, feature TEXT NOT NULL, enabled INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, feature));
"""

_PUBLIC_USER = ("id", "tenant_id", "email", "role", "name", "created_at")


class SqliteIdentityRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)
        if not self.get_plan(entitlements.DEFAULT_PLAN_ID):
            self.create_plan(entitlements.DEFAULT_PLAN_ID,
                             entitlements.DEFAULT_PLAN_NAME,
                             list(entitlements.FEATURES))

    # -- users --------------------------------------------------------------
    @staticmethod
    def _public(row: dict) -> dict:
        return {k: row[k] for k in _PUBLIC_USER}

    def create_user(self, tenant_id, email, pw_salt, pw_hash, role, name) -> dict:
        import sqlite3
        uid = new_id()
        try:
            self.db.execute(
                "INSERT INTO users (id, tenant_id, email, pw_salt, pw_hash, "
                "role, name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, tenant_id, email, pw_salt, pw_hash, role, name or "",
                 utcnow_iso()))
        except sqlite3.IntegrityError:
            raise ValueError(f"a user with email {email} already exists in "
                             "this tenant")
        return self.get_user(uid)

    def get_user(self, user_id) -> dict | None:
        row = self.db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._public(dict(row)) if row else None

    def get_by_email_raw(self, tenant_id, email) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM users WHERE tenant_id = ? AND email = ?",
            (tenant_id, email))
        return dict(row) if row else None

    def get_user_raw(self, user_id) -> dict | None:
        row = self.db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return dict(row) if row else None

    def set_mfa(self, user_id, secret, enabled) -> None:
        self.db.execute(
            "UPDATE users SET mfa_secret = ?, mfa_enabled = ? WHERE id = ?",
            (secret, 1 if enabled else 0, user_id))

    def list_users(self, tenant_id) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,))
        return [self._public(dict(r)) for r in rows]

    # -- sessions -----------------------------------------------------------
    def create_session(self, token, user, expires_at) -> None:
        self.db.execute(
            "INSERT INTO sessions (token, user_id, tenant_id, role, email, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, user["id"], user["tenant_id"], user["role"], user["email"],
             utcnow_iso(), expires_at))

    def get_session(self, token) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM sessions WHERE token = ?", (token,))
        return dict(row) if row else None

    def delete_session(self, token) -> None:
        self.db.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def delete_sessions_for_tenant(self, tenant_id) -> None:
        self.db.execute("DELETE FROM sessions WHERE tenant_id = ?", (tenant_id,))

    # -- tenants ------------------------------------------------------------
    def create_tenant(self, tenant_id, name, plan_id, status) -> dict:
        self.db.execute(
            "INSERT INTO tenants (id, name, plan_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tenant_id, name, plan_id, status, utcnow_iso()))
        return self.get_tenant(tenant_id)

    def get_tenant(self, tenant_id) -> dict | None:
        row = self.db.fetchone("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        return dict(row) if row else None

    def list_tenants(self) -> list[dict]:
        return [dict(r) for r in self.db.fetchall(
            "SELECT * FROM tenants ORDER BY created_at")]

    def set_tenant_plan(self, tenant_id, plan_id) -> dict | None:
        self.db.execute("UPDATE tenants SET plan_id = ? WHERE id = ?",
                        (plan_id, tenant_id))
        return self.get_tenant(tenant_id)

    def set_tenant_status(self, tenant_id, status) -> dict | None:
        self.db.execute("UPDATE tenants SET status = ? WHERE id = ?",
                        (status, tenant_id))
        return self.get_tenant(tenant_id)

    # -- plans + overrides --------------------------------------------------
    def create_plan(self, plan_id, name, features) -> dict:
        self.db.execute(
            "INSERT INTO plans (id, name, features, created_at) "
            "VALUES (?, ?, ?, ?)",
            (plan_id, name, json.dumps(list(features)), utcnow_iso()))
        return self.get_plan(plan_id)

    def get_plan(self, plan_id) -> dict | None:
        row = self.db.fetchone("SELECT * FROM plans WHERE id = ?", (plan_id,))
        if not row:
            return None
        rec = dict(row)
        rec["features"] = json.loads(rec["features"])
        return rec

    def list_plans(self) -> list[dict]:
        out = []
        for r in self.db.fetchall("SELECT * FROM plans ORDER BY created_at"):
            rec = dict(r)
            rec["features"] = json.loads(rec["features"])
            out.append(rec)
        return out

    def set_override(self, tenant_id, feature, enabled) -> None:
        self.db.execute(
            "INSERT INTO overrides (tenant_id, feature, enabled) "
            "VALUES (?, ?, ?) ON CONFLICT(tenant_id, feature) "
            "DO UPDATE SET enabled = excluded.enabled",
            (tenant_id, feature, 1 if enabled else 0))

    def list_overrides(self, tenant_id) -> dict:
        rows = self.db.fetchall(
            "SELECT feature, enabled FROM overrides WHERE tenant_id = ?",
            (tenant_id,))
        return {r["feature"]: bool(r["enabled"]) for r in rows}
