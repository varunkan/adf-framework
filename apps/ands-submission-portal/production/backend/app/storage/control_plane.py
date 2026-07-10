"""Postgres-backed multi-tenant control plane (REQ-077..084, REQ-091).

Mirrors monolith auth/tenancy/entitlements behaviour using tenant-scoped rows
in PostgreSQL instead of per-tenant SQLite files.
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .. import domain_path  # noqa: F401 — portal modules on sys.path
import auth
import entitlements

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_DELETED = "deleted"

CONTROL_PLANE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cp_tenants (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    slug                TEXT UNIQUE NOT NULL,
    registration_email  TEXT UNIQUE NOT NULL,
    plan_id             TEXT NOT NULL,
    status              TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cp_users (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    email       TEXT NOT NULL,
    pw_salt     TEXT NOT NULL,
    pw_hash     TEXT NOT NULL,
    role        TEXT NOT NULL,
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, email)
);

CREATE TABLE IF NOT EXISTS cp_sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS cp_plans (
    id          TEXT PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    features    JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cp_overrides (
    tenant_id   TEXT NOT NULL,
    feature     TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL,
    PRIMARY KEY (tenant_id, feature)
);

CREATE TABLE IF NOT EXISTS cp_audit (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    tenant_id   TEXT,
    before_json JSONB,
    after_json  JSONB
);

CREATE TABLE IF NOT EXISTS tenant_records (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenant_records_tenant_kind
    ON tenant_records (tenant_id, kind);
"""


class DuplicateTenant(Exception):
    def __init__(self, existing: dict) -> None:
        self.existing = existing
        super().__init__("tenant already registered")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or "tenant"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ControlPlaneStore:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://", "postgresql://", 1
            )
        self._pool = ConnectionPool(
            conninfo=database_url,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=10,
        )
        self.init_schema()

    def init_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(CONTROL_PLANE_SCHEMA)
            row = conn.execute(
                "SELECT id FROM cp_plans WHERE id = %s",
                (entitlements.DEFAULT_PLAN_ID,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO cp_plans (id, name, features, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        entitlements.DEFAULT_PLAN_ID,
                        entitlements.DEFAULT_PLAN_NAME,
                        json.dumps(list(entitlements.FEATURES)),
                        _now(),
                    ),
                )

    @contextmanager
    def _connection(self):
        with self._pool.connection() as conn:
            yield conn
            conn.commit()

    def close(self) -> None:
        self._pool.close()

    # -- tenants (REQ-077) --------------------------------------------------
    def create_tenant(
        self,
        company: str,
        registration_email: str,
        *,
        actor: str = "self-serve",
        plan_id: str | None = None,
    ) -> dict:
        email = (registration_email or "").strip().lower()
        if not company.strip() or not email or "@" not in email:
            raise ValueError("company and valid registration email required")
        existing = self.get_tenant_by_email(email)
        if existing is not None:
            raise DuplicateTenant(existing)
        tenant_id = uuid.uuid4().hex
        slug = self._unique_slug(company)
        plan = plan_id or entitlements.DEFAULT_PLAN_ID
        created_at = _now()
        tenant = {
            "id": tenant_id,
            "name": company.strip(),
            "slug": slug,
            "registration_email": email,
            "plan_id": plan,
            "status": STATUS_ACTIVE,
            "created_at": created_at.isoformat(),
        }
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO cp_tenants
                    (id, name, slug, registration_email, plan_id, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    tenant["name"],
                    slug,
                    email,
                    plan,
                    STATUS_ACTIVE,
                    created_at,
                ),
            )
        self.audit(actor, "tenant.create", tenant_id=tenant_id, after=tenant)
        return tenant

    def _unique_slug(self, base: str) -> str:
        slug = _slugify(base)
        candidate, n = slug, 1
        while self.get_tenant_by_slug(candidate) is not None:
            n += 1
            candidate = f"{slug}-{n}"
        return candidate

    def get_tenant(self, tenant_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cp_tenants WHERE id = %s", (tenant_id,)
            ).fetchone()
        return _tenant_row(row) if row else None

    def get_tenant_by_email(self, email: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cp_tenants WHERE registration_email = %s",
                ((email or "").strip().lower(),),
            ).fetchone()
        return _tenant_row(row) if row else None

    def get_tenant_by_slug(self, slug: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cp_tenants WHERE slug = %s", (slug,)
            ).fetchone()
        return _tenant_row(row) if row else None

    def list_tenants(self, include_deleted: bool = False) -> list[dict]:
        with self._connection() as conn:
            if include_deleted:
                rows = conn.execute(
                    "SELECT * FROM cp_tenants ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cp_tenants WHERE status != %s ORDER BY created_at",
                    (STATUS_DELETED,),
                ).fetchall()
        return [_tenant_row(r) for r in rows]

    def delete_tenant(
        self, tenant_id: str, actor: str, *, archive: bool = True
    ) -> None:
        before = self.get_tenant(tenant_id)
        if before is None:
            return
        after = dict(before, status=STATUS_DELETED)
        with self._connection() as conn:
            conn.execute(
                "UPDATE cp_tenants SET status = %s WHERE id = %s",
                (STATUS_DELETED, tenant_id),
            )
        self.audit(
            actor, "tenant.delete", tenant_id=tenant_id, before=before, after=after
        )

    # -- auth (REQ-077/083) -------------------------------------------------
    def create_user(
        self,
        tenant_id: str,
        email: str,
        password: str,
        *,
        role: str = auth.USER_ROLE,
        name: str = "",
    ) -> dict:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("a valid email is required")
        if role not in auth.ROLES:
            raise ValueError(f"unknown role: {role}")
        salt, pw_hash = auth.hash_password(password)
        uid = uuid.uuid4().hex
        created_at = _now()
        with self._connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO cp_users
                        (id, tenant_id, email, pw_salt, pw_hash, role, name, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uid,
                        tenant_id or auth.PLATFORM_TENANT,
                        email,
                        salt,
                        pw_hash,
                        role,
                        name or "",
                        created_at,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError(
                    f"a user with email {email} already exists in this tenant"
                ) from exc
        return self.get_user(uid)

    def get_user(self, user_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cp_users WHERE id = %s", (user_id,)
            ).fetchone()
        return _user_row(row) if row else None

    def authenticate(
        self, tenant_id: str, email: str, password: str
    ) -> dict | None:
        email = (email or "").strip().lower()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cp_users WHERE tenant_id = %s AND email = %s",
                (tenant_id, email),
            ).fetchone()
        if row is None:
            return None
        if not auth.verify_password(password, row["pw_salt"], row["pw_hash"]):
            return None
        return _user_row(row)

    def start_session(self, user: dict) -> str:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        created = _now()
        expires = created + timedelta(hours=12)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO cp_sessions
                    (token, user_id, tenant_id, role, email, created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    token,
                    user["id"],
                    user["tenant_id"],
                    user["role"],
                    user["email"],
                    created,
                    expires,
                ),
            )
        return token

    def resolve_session(self, token: str) -> dict | None:
        if not token:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cp_sessions WHERE token = %s", (token,)
            ).fetchone()
        if row is None:
            return None
        expires = row["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < _now():
            self.end_session(token)
            return None
        return {
            "token": row["token"],
            "user_id": row["user_id"],
            "tenant_id": row["tenant_id"],
            "role": row["role"],
            "email": row["email"],
        }

    def end_session(self, token: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM cp_sessions WHERE token = %s", (token,))

    # -- entitlements (REQ-081/082) -----------------------------------------
    def effective_features(self, tenant_id: str, plan_id: str) -> dict[str, bool]:
        with self._connection() as conn:
            plan_row = conn.execute(
                "SELECT features FROM cp_plans WHERE id = %s", (plan_id,)
            ).fetchone()
            if plan_row is None:
                features = list(entitlements.FEATURES)
            else:
                raw = plan_row["features"]
                features = raw if isinstance(raw, list) else json.loads(raw)
            overrides = conn.execute(
                "SELECT feature, enabled FROM cp_overrides WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchall()
        base = {f: True for f in entitlements.normalize_features(features)}
        for row in overrides:
            base[row["feature"]] = bool(row["enabled"])
        return base

    def require_feature(self, session: dict, feature: str) -> bool:
        tenant = self.get_tenant(session["tenant_id"])
        if tenant is None:
            return False
        effective = self.effective_features(tenant["id"], tenant["plan_id"])
        return effective.get(feature, False)

    # -- tenant workspace records (REQ-078) ---------------------------------
    def add_record(self, tenant_id: str, kind: str, payload: dict) -> dict:
        created_at = _now()
        with self._connection() as conn:
            row = conn.execute(
                """
                INSERT INTO tenant_records (tenant_id, kind, payload, created_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id, tenant_id, kind, payload, created_at
                """,
                (tenant_id, kind, json.dumps(payload), created_at),
            ).fetchone()
        return _record_row(row)

    def list_records(self, tenant_id: str, kind: str = "") -> list[dict]:
        with self._connection() as conn:
            if kind:
                rows = conn.execute(
                    """
                    SELECT id, tenant_id, kind, payload, created_at
                    FROM tenant_records
                    WHERE tenant_id = %s AND kind = %s
                    ORDER BY id
                    """,
                    (tenant_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, tenant_id, kind, payload, created_at
                    FROM tenant_records
                    WHERE tenant_id = %s
                    ORDER BY id
                    """,
                    (tenant_id,),
                ).fetchall()
        return [_record_row(r) for r in rows]

    def record_count(self, tenant_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM tenant_records WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()
        return int(row["n"])

    # -- audit (REQ-084) ----------------------------------------------------
    def audit(
        self,
        actor: str,
        action: str,
        *,
        tenant_id: str = "",
        before=None,
        after=None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO cp_audit
                    (actor, action, tenant_id, before_json, after_json)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    actor,
                    action,
                    tenant_id or None,
                    json.dumps(before) if before is not None else None,
                    json.dumps(after) if after is not None else None,
                ),
            )


def _tenant_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "registration_email": row["registration_email"],
        "plan_id": row["plan_id"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else row["created_at"],
    }


def _user_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "email": row["email"],
        "role": row["role"],
        "name": row["name"],
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else row["created_at"],
    }


def _record_row(row: dict) -> dict:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "kind": row["kind"],
        "payload": payload,
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else row["created_at"],
    }
