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
    expires_at TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'full');
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, plan_id TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL,
    billing_status TEXT NOT NULL DEFAULT 'active', grace_until TEXT,
    require_mfa INTEGER NOT NULL DEFAULT 0,
    require_sod INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, features TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS overrides (
    tenant_id TEXT NOT NULL, feature TEXT NOT NULL, enabled INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, feature));
CREATE TABLE IF NOT EXISTS reset_codes (
    email TEXT PRIMARY KEY, code_salt TEXT NOT NULL, code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL);
-- CAMP-SSO-OIDC: per-workspace OIDC client config (one row per tenant).
CREATE TABLE IF NOT EXISTS sso_config (
    tenant_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
    issuer TEXT NOT NULL DEFAULT '', client_id TEXT NOT NULL DEFAULT '',
    client_secret TEXT NOT NULL DEFAULT '', redirect_uri TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '');
-- CAMP-SSO-OIDC: in-flight OIDC login round-trips (state → nonce/verifier).
CREATE TABLE IF NOT EXISTS sso_flows (
    state TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, nonce TEXT NOT NULL,
    code_verifier TEXT NOT NULL, redirect_uri TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
"""

_PUBLIC_USER = ("id", "tenant_id", "email", "role", "name", "created_at")


class SqliteIdentityRepository:
    def __init__(self, db: SqliteDb | None = None) -> None:
        self.db = db or SqliteDb(":memory:")
        self.db.executescript(_SCHEMA)
        self._migrate()
        if not self.get_plan(entitlements.DEFAULT_PLAN_ID):
            self.create_plan(entitlements.DEFAULT_PLAN_ID,
                             entitlements.DEFAULT_PLAN_NAME,
                             list(entitlements.FEATURES))

    def _migrate(self) -> None:
        # add columns introduced after the original schema on already-created DBs
        cols = {r["name"] for r in self.db.fetchall("PRAGMA table_info(tenants)")}
        if "require_mfa" not in cols:
            self.db.execute("ALTER TABLE tenants ADD COLUMN require_mfa "
                            "INTEGER NOT NULL DEFAULT 0")
        # TIER3-SOD-ENFORCE: per-workspace 'enforce segregation of duties' policy
        if "require_sod" not in cols:
            self.db.execute("ALTER TABLE tenants ADD COLUMN require_sod "
                            "INTEGER NOT NULL DEFAULT 0")
        scols = {r["name"] for r in self.db.fetchall(
            "PRAGMA table_info(sessions)")}
        if "scope" not in scols:
            # WS4 fix: existing sessions predate scoping — treat them as full.
            self.db.execute("ALTER TABLE sessions ADD COLUMN scope TEXT "
                            "NOT NULL DEFAULT 'full'")
        # CAMP-SSO-OIDC: sessions carry whether the principal is IdP-VERIFIED
        # (SSO login) vs a recorded email (password login), + the issuer/subject.
        if "identity_verified" not in scols:
            self.db.execute("ALTER TABLE sessions ADD COLUMN identity_verified "
                            "INTEGER NOT NULL DEFAULT 0")
            self.db.execute("ALTER TABLE sessions ADD COLUMN identity_issuer "
                            "TEXT NOT NULL DEFAULT ''")
            self.db.execute("ALTER TABLE sessions ADD COLUMN identity_subject "
                            "TEXT NOT NULL DEFAULT ''")
        # CAMP-SSO-OIDC: a user bound to an IdP subject carries it durably, so
        # the SoD/e-sign records can name an authenticated principal.
        ucols = {r["name"] for r in self.db.fetchall(
            "PRAGMA table_info(users)")}
        if "idp_subject" not in ucols:
            self.db.execute("ALTER TABLE users ADD COLUMN idp_subject TEXT "
                            "NOT NULL DEFAULT ''")
            self.db.execute("ALTER TABLE users ADD COLUMN idp_issuer TEXT "
                            "NOT NULL DEFAULT ''")

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

    def find_by_email_raw(self, email) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM users WHERE email = ?", (email,))
        return [dict(r) for r in rows]

    def get_user_raw(self, user_id) -> dict | None:
        row = self.db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return dict(row) if row else None

    def update_password(self, user_id, pw_salt, pw_hash) -> None:
        self.db.execute(
            "UPDATE users SET pw_salt = ?, pw_hash = ? WHERE id = ?",
            (pw_salt, pw_hash, user_id))

    # -- password reset codes -------------------------------------------------
    def save_reset_code(self, email, code_salt, code_hash, expires_at) -> None:
        self.db.execute(
            "INSERT INTO reset_codes (email, code_salt, code_hash, expires_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
            "code_salt = excluded.code_salt, code_hash = excluded.code_hash, "
            "expires_at = excluded.expires_at", (email, code_salt, code_hash,
                                                 expires_at))

    def get_reset_code(self, email) -> dict | None:
        return self.db.fetchone(
            "SELECT * FROM reset_codes WHERE email = ?", (email,))

    def delete_reset_code(self, email) -> None:
        self.db.execute("DELETE FROM reset_codes WHERE email = ?", (email,))

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
    def create_session(self, token, user, expires_at, scope="full",
                       identity=None) -> None:
        identity = identity or {}
        self.db.execute(
            "INSERT INTO sessions (token, user_id, tenant_id, role, email, "
            "created_at, expires_at, scope, identity_verified, "
            "identity_issuer, identity_subject) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (token, user["id"], user["tenant_id"], user["role"], user["email"],
             utcnow_iso(), expires_at, scope,
             1 if identity.get("verified") else 0,
             identity.get("issuer") or "", identity.get("subject") or ""))

    def get_session(self, token) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM sessions WHERE token = ?", (token,))
        return dict(row) if row else None

    def delete_session(self, token) -> None:
        self.db.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def delete_sessions_for_user(self, user_id) -> None:
        self.db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def delete_sessions_for_tenant(self, tenant_id) -> None:
        self.db.execute("DELETE FROM sessions WHERE tenant_id = ?", (tenant_id,))

    def delete_sessions_for_tenant_without_mfa(self, tenant_id) -> None:
        # WS4 fix (revoke-on-mandate-on): drop full sessions of tenant members
        # who have no verified MFA, so flipping the mandate on takes effect now.
        # IdP-verified (SSO) sessions are kept — the mandate governs password
        # credentials; federated authentication strength is the IdP's policy
        # (mirrors the _session_blocked_by_mandate exemption).
        self.db.execute(
            "DELETE FROM sessions WHERE tenant_id = ? AND "
            "COALESCE(identity_verified, 0) = 0 AND user_id IN ("
            "SELECT id FROM users WHERE tenant_id = ? AND "
            "COALESCE(mfa_enabled, 0) = 0)", (tenant_id, tenant_id))

    # -- tenants ------------------------------------------------------------
    def create_tenant(self, tenant_id, name, plan_id, status) -> dict:
        # Round-9 onboarding item 4: NEW workspaces default to 'MFA Required'
        # (require_mfa=1), enforced at sign-in for every member; relaxing it is
        # an explicit admin action. The DDL default stays 0 so PRE-EXISTING
        # workspaces are not silently flipped into a lockout.
        self.db.execute(
            "INSERT INTO tenants (id, name, plan_id, status, require_mfa, "
            "created_at) VALUES (?, ?, ?, ?, 1, ?)",
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

    def set_billing(self, tenant_id, billing_status, grace_until) -> dict | None:
        self.db.execute(
            "UPDATE tenants SET billing_status = ?, grace_until = ? WHERE id = ?",
            (billing_status, grace_until, tenant_id))
        return self.get_tenant(tenant_id)

    def set_require_mfa(self, tenant_id, require_mfa) -> dict | None:
        self.db.execute("UPDATE tenants SET require_mfa = ? WHERE id = ?",
                        (1 if require_mfa else 0, tenant_id))
        return self.get_tenant(tenant_id)

    def set_require_sod(self, tenant_id, require_sod) -> dict | None:
        self.db.execute("UPDATE tenants SET require_sod = ? WHERE id = ?",
                        (1 if require_sod else 0, tenant_id))
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

    # -- CAMP-SSO-OIDC: workspace SSO config + in-flight login state ---------
    def set_sso_config(self, tenant_id, enabled, issuer, client_id,
                       client_secret, redirect_uri) -> dict:
        self.db.execute(
            "INSERT INTO sso_config (tenant_id, enabled, issuer, client_id, "
            "client_secret, redirect_uri, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(tenant_id) DO UPDATE SET "
            "enabled = excluded.enabled, issuer = excluded.issuer, "
            "client_id = excluded.client_id, "
            "client_secret = excluded.client_secret, "
            "redirect_uri = excluded.redirect_uri, "
            "updated_at = excluded.updated_at",
            (tenant_id, 1 if enabled else 0, issuer, client_id, client_secret,
             redirect_uri, utcnow_iso()))
        return self.get_sso_config(tenant_id)

    def get_sso_config(self, tenant_id) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM sso_config WHERE tenant_id = ?", (tenant_id,))
        if not row:
            return None
        rec = dict(row)
        rec["enabled"] = bool(rec["enabled"])
        return rec

    def create_sso_flow(self, state, tenant_id, nonce, code_verifier,
                        redirect_uri, expires_at) -> None:
        self.db.execute(
            "INSERT INTO sso_flows (state, tenant_id, nonce, code_verifier, "
            "redirect_uri, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (state, tenant_id, nonce, code_verifier, redirect_uri,
             utcnow_iso(), expires_at))

    def get_sso_flow(self, state) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM sso_flows WHERE state = ?", (state,))
        return dict(row) if row else None

    def delete_sso_flow(self, state) -> None:
        self.db.execute("DELETE FROM sso_flows WHERE state = ?", (state,))

    # -- CAMP-SSO-OIDC: bind a user to a verified IdP subject ----------------
    def get_user_by_idp(self, tenant_id, issuer, subject) -> dict | None:
        row = self.db.fetchone(
            "SELECT * FROM users WHERE tenant_id = ? AND idp_issuer = ? AND "
            "idp_subject = ?", (tenant_id, issuer, subject))
        return dict(row) if row else None

    def bind_idp(self, user_id, issuer, subject) -> None:
        self.db.execute(
            "UPDATE users SET idp_issuer = ?, idp_subject = ? WHERE id = ?",
            (issuer, subject, user_id))
