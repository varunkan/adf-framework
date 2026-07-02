"""Postgres repository adapter (production) — pg8000. Same contract as SQLite."""

from __future__ import annotations

import json
import threading

from ands_shared import new_id, utcnow_iso

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
    status TEXT NOT NULL, created_at TEXT NOT NULL,
    billing_status TEXT NOT NULL DEFAULT 'active', grace_until TEXT);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, features TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS overrides (
    tenant_id TEXT NOT NULL, feature TEXT NOT NULL, enabled INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, feature));
CREATE TABLE IF NOT EXISTS reset_codes (
    email TEXT PRIMARY KEY, code_salt TEXT NOT NULL, code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL);
"""

_PUBLIC_USER = ("id", "tenant_id", "email", "role", "name", "created_at")


class PostgresIdentityRepository:
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
        if not self.get_plan(entitlements.DEFAULT_PLAN_ID):
            self.create_plan(entitlements.DEFAULT_PLAN_ID,
                             entitlements.DEFAULT_PLAN_NAME,
                             list(entitlements.FEATURES))

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

    def _one(self, sql, params=()):
        rows = self._all(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _public(row):
        return {k: row[k] for k in _PUBLIC_USER}

    # users
    def create_user(self, tenant_id, email, pw_salt, pw_hash, role, name):
        if self.get_by_email_raw(tenant_id, email):
            raise ValueError(f"a user with email {email} already exists in "
                             "this tenant")
        uid = new_id()
        self._exec(
            "INSERT INTO users (id, tenant_id, email, pw_salt, pw_hash, role, "
            "name, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (uid, tenant_id, email, pw_salt, pw_hash, role, name or "",
             utcnow_iso()))
        return self.get_user(uid)

    def get_user(self, user_id):
        row = self._one("SELECT * FROM users WHERE id = %s", (user_id,))
        return self._public(row) if row else None

    def get_by_email_raw(self, tenant_id, email):
        return self._one("SELECT * FROM users WHERE tenant_id = %s AND "
                         "email = %s", (tenant_id, email))

    def get_user_raw(self, user_id):
        return self._one("SELECT * FROM users WHERE id = %s", (user_id,))

    def set_mfa(self, user_id, secret, enabled):
        self._exec("UPDATE users SET mfa_secret = %s, mfa_enabled = %s "
                   "WHERE id = %s", (secret, 1 if enabled else 0, user_id))

    def update_password(self, user_id, pw_salt, pw_hash):
        self._exec("UPDATE users SET pw_salt = %s, pw_hash = %s WHERE id = %s",
                   (pw_salt, pw_hash, user_id))

    # password reset codes
    def save_reset_code(self, email, code_salt, code_hash, expires_at):
        self._exec(
            "INSERT INTO reset_codes (email, code_salt, code_hash, expires_at) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (email) DO UPDATE SET "
            "code_salt = EXCLUDED.code_salt, code_hash = EXCLUDED.code_hash, "
            "expires_at = EXCLUDED.expires_at",
            (email, code_salt, code_hash, expires_at))

    def get_reset_code(self, email):
        return self._one("SELECT * FROM reset_codes WHERE email = %s", (email,))

    def delete_reset_code(self, email):
        self._exec("DELETE FROM reset_codes WHERE email = %s", (email,))

    def list_users(self, tenant_id):
        return [self._public(r) for r in self._all(
            "SELECT * FROM users WHERE tenant_id = %s ORDER BY created_at",
            (tenant_id,))]

    # sessions
    def create_session(self, token, user, expires_at):
        self._exec(
            "INSERT INTO sessions (token, user_id, tenant_id, role, email, "
            "created_at, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (token, user["id"], user["tenant_id"], user["role"], user["email"],
             utcnow_iso(), expires_at))

    def get_session(self, token):
        return self._one("SELECT * FROM sessions WHERE token = %s", (token,))

    def delete_session(self, token):
        self._exec("DELETE FROM sessions WHERE token = %s", (token,))

    def delete_sessions_for_user(self, user_id):
        self._exec("DELETE FROM sessions WHERE user_id = %s", (user_id,))

    def delete_sessions_for_tenant(self, tenant_id):
        self._exec("DELETE FROM sessions WHERE tenant_id = %s", (tenant_id,))

    # tenants
    def create_tenant(self, tenant_id, name, plan_id, status):
        self._exec("INSERT INTO tenants (id, name, plan_id, status, created_at) "
                   "VALUES (%s,%s,%s,%s,%s)",
                   (tenant_id, name, plan_id, status, utcnow_iso()))
        return self.get_tenant(tenant_id)

    def get_tenant(self, tenant_id):
        return self._one("SELECT * FROM tenants WHERE id = %s", (tenant_id,))

    def list_tenants(self):
        return self._all("SELECT * FROM tenants ORDER BY created_at")

    def set_tenant_plan(self, tenant_id, plan_id):
        self._exec("UPDATE tenants SET plan_id = %s WHERE id = %s",
                   (plan_id, tenant_id))
        return self.get_tenant(tenant_id)

    def set_tenant_status(self, tenant_id, status):
        self._exec("UPDATE tenants SET status = %s WHERE id = %s",
                   (status, tenant_id))
        return self.get_tenant(tenant_id)

    def set_billing(self, tenant_id, billing_status, grace_until):
        self._exec("UPDATE tenants SET billing_status = %s, grace_until = %s "
                   "WHERE id = %s", (billing_status, grace_until, tenant_id))
        return self.get_tenant(tenant_id)

    # plans + overrides
    def create_plan(self, plan_id, name, features):
        self._exec("INSERT INTO plans (id, name, features, created_at) "
                   "VALUES (%s,%s,%s,%s)",
                   (plan_id, name, json.dumps(list(features)), utcnow_iso()))
        return self.get_plan(plan_id)

    def get_plan(self, plan_id):
        row = self._one("SELECT * FROM plans WHERE id = %s", (plan_id,))
        if row:
            row["features"] = json.loads(row["features"])
        return row

    def list_plans(self):
        rows = self._all("SELECT * FROM plans ORDER BY created_at")
        for r in rows:
            r["features"] = json.loads(r["features"])
        return rows

    def set_override(self, tenant_id, feature, enabled):
        self._exec("INSERT INTO overrides (tenant_id, feature, enabled) "
                   "VALUES (%s,%s,%s) ON CONFLICT (tenant_id, feature) "
                   "DO UPDATE SET enabled = excluded.enabled",
                   (tenant_id, feature, 1 if enabled else 0))

    def list_overrides(self, tenant_id):
        return {r["feature"]: bool(r["enabled"]) for r in self._all(
            "SELECT feature, enabled FROM overrides WHERE tenant_id = %s",
            (tenant_id,))}
