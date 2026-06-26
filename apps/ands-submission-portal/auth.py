#!/usr/bin/env python3
"""Authentication + sessions for the multi-tenant control plane (REQ-077/083).

Identity has a strict hierarchy: a platform **owner** (super-admin) sits above
all tenants and lives only in the control plane (``tenant_id`` is empty); within
each tenant there is a **tenant-admin** and ordinary **users**. A user is unique
per ``(tenant_id, email)`` so the same person can exist in two tenants without
collision, and a credential for tenant A can never authenticate into tenant B
(REQ-083).

Passwords are stored salted + hashed with PBKDF2-HMAC-SHA256 (stdlib ``hashlib``)
— never in clear. Sessions are opaque ``secrets`` tokens with an expiry. All of
this is platform data and lives in the SEPARATE control-plane DB (REQ-078).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

OWNER_ROLE = "owner"
TENANT_ADMIN_ROLE = "tenant-admin"
USER_ROLE = "user"
ROLES = (OWNER_ROLE, TENANT_ADMIN_ROLE, USER_ROLE)

# Owner accounts have no tenant — this sentinel keeps the UNIQUE(tenant_id,email)
# constraint meaningful while marking the platform/control-plane scope.
PLATFORM_TENANT = ""

_PBKDF2_ITERS = 120_000
_SESSION_TTL = timedelta(hours=12)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: str = "") -> tuple[str, str]:
    """Return ``(salt_hex, hash_hex)`` for *password* (new salt if none given)."""
    if not isinstance(password, str) or password == "":
        raise ValueError("password is required")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERS)
    return salt, digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    if not password or not salt_hex or not hash_hex:
        return False
    try:
        _, candidate = hash_password(password, salt_hex)
    except ValueError:
        return False
    return hmac.compare_digest(candidate, hash_hex)


class AuthStore:
    """Users + sessions in the control-plane DB."""

    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS users (
                       id TEXT PRIMARY KEY,
                       tenant_id TEXT NOT NULL,
                       email TEXT NOT NULL,
                       pw_salt TEXT NOT NULL,
                       pw_hash TEXT NOT NULL,
                       role TEXT NOT NULL,
                       name TEXT,
                       created_at TEXT NOT NULL,
                       UNIQUE (tenant_id, email))""")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                       token TEXT PRIMARY KEY,
                       user_id TEXT NOT NULL,
                       tenant_id TEXT NOT NULL,
                       role TEXT NOT NULL,
                       email TEXT NOT NULL,
                       created_at TEXT NOT NULL,
                       expires_at TEXT NOT NULL)""")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- users --------------------------------------------------------------
    @staticmethod
    def _public_user(row) -> dict:
        return {"id": row["id"], "tenant_id": row["tenant_id"],
                "email": row["email"], "role": row["role"],
                "name": row["name"], "created_at": row["created_at"]}

    def create_user(self, tenant_id: str, email: str, password: str,
                    role: str = USER_ROLE, name: str = "") -> dict:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("a valid email is required")
        if role not in ROLES:
            raise ValueError(f"unknown role: {role}")
        salt, pw_hash = hash_password(password)
        uid = uuid.uuid4().hex
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO users (id, tenant_id, email, pw_salt, "
                    "pw_hash, role, name, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, tenant_id or PLATFORM_TENANT, email, salt, pw_hash,
                     role, name or "", _now().isoformat()))
                self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(
                f"a user with email {email} already exists in this tenant")
        return self.get_user(uid)

    def get_user(self, user_id: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._public_user(row) if row else None

    def get_by_email(self, tenant_id: str, email: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE tenant_id = ? AND email = ?",
                (tenant_id or PLATFORM_TENANT, (email or "").strip().lower())
            ).fetchone()
        return row  # raw row (has pw fields) for internal auth use

    def list_users(self, tenant_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at",
                (tenant_id or PLATFORM_TENANT,)).fetchall()
        return [self._public_user(r) for r in rows]

    def authenticate(self, tenant_id: str, email: str, password: str):
        """Return the public user dict on success, else ``None``. Scoped to a
        single tenant — a tenant-A credential never matches in tenant B."""
        row = self.get_by_email(tenant_id, email)
        if row is None:
            return None
        if not verify_password(password, row["pw_salt"], row["pw_hash"]):
            return None
        return self._public_user(row)

    def authenticate_owner(self, email: str, password: str):
        return self.authenticate(PLATFORM_TENANT, email, password)

    # -- sessions -----------------------------------------------------------
    def start_session(self, user: dict) -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (token, user_id, tenant_id, role, "
                "email, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (token, user["id"], user["tenant_id"], user["role"],
                 user["email"], now.isoformat(),
                 (now + _SESSION_TTL).isoformat()))
            self._conn.commit()
        return token

    def resolve_session(self, token: str):
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        if row is None:
            return None
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return None
        if expires < _now():
            self.end_session(token)
            return None
        return {"token": row["token"], "user_id": row["user_id"],
                "tenant_id": row["tenant_id"], "role": row["role"],
                "email": row["email"]}

    def end_session(self, token: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions WHERE token = ?", (token,))
            self._conn.commit()

    def end_sessions_for_tenant(self, tenant_id: str) -> None:
        """Used when a tenant is suspended/deleted — kill all live sessions."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions WHERE tenant_id = ?", (tenant_id,))
            self._conn.commit()

    # -- bootstrap ----------------------------------------------------------
    def ensure_owner(self, email: str, password: str) -> dict:
        """Idempotently ensure a platform-owner account exists (server boot)."""
        existing = self.get_by_email(PLATFORM_TENANT, email)
        if existing is not None:
            return self._public_user(existing)
        return self.create_user(PLATFORM_TENANT, email, password,
                                role=OWNER_ROLE, name="Platform Owner")
