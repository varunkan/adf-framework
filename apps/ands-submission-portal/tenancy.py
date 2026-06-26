#!/usr/bin/env python3
"""Tenant registry, per-tenant DB isolation, lifecycle + control-plane audit.

REQ-077  every tenant has an immutable id; created via self-serve sign-up OR
         owner provisioning; default all-features plan.
REQ-078  each tenant's data lives in its OWN sqlite file
         (``<root>/<tenant-id>/ands.db``); platform data is a SEPARATE DB; no
         request may touch another tenant's file; an unresolved tenant is denied.
REQ-084  owner can suspend / resume / delete a tenant; every lifecycle and
         entitlement action is written to the control-plane audit with actor,
         timestamp and before/after state.

Pure stdlib (sqlite3 + os). The control-plane registry/audit is one DB; each
tenant's workspace data is a physically separate file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_DELETED = "deleted"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or "tenant"


class TenantData:
    """A single tenant's OWN workspace database (physically isolated file).

    This is intentionally minimal — it proves real per-tenant persistence and
    isolation (REQ-078). Each tenant's REQ-001..076 records would live here,
    keyed to nothing but this file, so one tenant can never read another's rows.
    """

    def __init__(self, db_path: str):
        # Caller is responsible for ensuring the parent dir exists.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS records (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   kind TEXT NOT NULL,
                   payload TEXT NOT NULL,
                   created_at TEXT NOT NULL)""")
        self._conn.commit()

    def add(self, kind: str, payload: dict) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO records (kind, payload, created_at) "
                "VALUES (?, ?, ?)",
                (kind, json.dumps(payload), _now()))
            self._conn.commit()
            rid = cur.lastrowid
        return {"id": rid, "kind": kind, "payload": payload}

    def list(self, kind: str = "") -> list[dict]:
        with self._lock:
            if kind:
                rows = self._conn.execute(
                    "SELECT * FROM records WHERE kind = ? ORDER BY id",
                    (kind,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM records ORDER BY id").fetchall()
        return [{"id": r["id"], "kind": r["kind"],
                 "payload": json.loads(r["payload"]),
                 "created_at": r["created_at"]} for r in rows]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM records").fetchone()
        return int(row["n"])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class TenancyStore:
    """Control-plane registry of tenants + the owner-action audit trail."""

    def __init__(self, db_path: str = ":memory:", tenants_root: str = ""):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # Where per-tenant DB files live. In-memory control plane (tests) keeps
        # tenant files in a sibling temp dir the caller supplies.
        self._root = tenants_root or os.path.join(
            os.path.dirname(os.path.abspath(db_path))
            if db_path != ":memory:" else ".", "data", "tenants")
        self._archive = os.path.join(self._root, "_archived")
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS tenants (
                       id TEXT PRIMARY KEY,
                       name TEXT NOT NULL,
                       slug TEXT UNIQUE NOT NULL,
                       registration_email TEXT UNIQUE NOT NULL,
                       plan_id TEXT NOT NULL,
                       status TEXT NOT NULL,
                       created_at TEXT NOT NULL)""")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS control_plane_audit (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       ts TEXT NOT NULL,
                       actor TEXT NOT NULL,
                       action TEXT NOT NULL,
                       tenant_id TEXT,
                       before TEXT,
                       after TEXT)""")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- paths (REQ-078) ----------------------------------------------------
    def tenant_db_path(self, tenant_id: str) -> str:
        path = os.path.join(self._root, tenant_id, "ands.db")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    # -- audit (REQ-084) ----------------------------------------------------
    def audit(self, actor: str, action: str, tenant_id: str = "",
              before=None, after=None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO control_plane_audit "
                "(ts, actor, action, tenant_id, before, after) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), actor, action, tenant_id,
                 json.dumps(before) if before is not None else None,
                 json.dumps(after) if after is not None else None))
            self._conn.commit()

    def list_audit(self, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM control_plane_audit ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "actor": r["actor"],
                 "action": r["action"], "tenant_id": r["tenant_id"],
                 "before": json.loads(r["before"]) if r["before"] else None,
                 "after": json.loads(r["after"]) if r["after"] else None}
                for r in rows]

    # -- registry (REQ-077) -------------------------------------------------
    @staticmethod
    def _row_to_tenant(row) -> dict:
        return {"id": row["id"], "name": row["name"], "slug": row["slug"],
                "registration_email": row["registration_email"],
                "plan_id": row["plan_id"], "status": row["status"],
                "created_at": row["created_at"]}

    def get_tenant(self, tenant_id: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        return self._row_to_tenant(row) if row else None

    def get_by_email(self, registration_email: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tenants WHERE registration_email = ?",
                ((registration_email or "").strip().lower(),)).fetchone()
        return self._row_to_tenant(row) if row else None

    def list_tenants(self, include_deleted: bool = False) -> list[dict]:
        with self._lock:
            if include_deleted:
                rows = self._conn.execute(
                    "SELECT * FROM tenants ORDER BY created_at").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM tenants WHERE status != ? "
                    "ORDER BY created_at", (STATUS_DELETED,)).fetchall()
        return [self._row_to_tenant(r) for r in rows]

    def _unique_slug(self, base: str) -> str:
        slug = _slugify(base)
        candidate, n = slug, 1
        while self._conn.execute(
                "SELECT 1 FROM tenants WHERE slug = ?",
                (candidate,)).fetchone() is not None:
            n += 1
            candidate = f"{slug}-{n}"
        return candidate

    def create_tenant(self, name: str, registration_email: str,
                      actor: str = "self-serve",
                      plan_id: str = "all-features") -> dict:
        """Create a tenant atomically. On a duplicate registration email this
        does NOT silently duplicate — it raises ``DuplicateTenant`` carrying the
        existing tenant so the caller can route to it (REQ-077)."""
        name = (name or "").strip()
        email = (registration_email or "").strip().lower()
        if not name:
            raise ValueError("company name is required")
        if not email or "@" not in email:
            raise ValueError("a valid registration email is required")
        existing = self.get_by_email(email)
        if existing is not None:
            raise DuplicateTenant(existing)
        tenant_id = uuid.uuid4().hex
        with self._lock:
            slug = self._unique_slug(name)
            self._conn.execute(
                "INSERT INTO tenants (id, name, slug, registration_email, "
                "plan_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tenant_id, name, slug, email, plan_id, STATUS_ACTIVE, _now()))
            self._conn.commit()
        tenant = self.get_tenant(tenant_id)
        # Materialise the tenant's own DB file up front (REQ-078).
        TenantData(self.tenant_db_path(tenant_id)).close()
        self.audit(actor, "tenant.create", tenant_id, None, tenant)
        return tenant

    # -- lifecycle (REQ-084) ------------------------------------------------
    def _set_status(self, tenant_id: str, status: str, actor: str) -> dict:
        before = self.get_tenant(tenant_id)
        if before is None:
            raise KeyError(tenant_id)
        with self._lock:
            self._conn.execute(
                "UPDATE tenants SET status = ? WHERE id = ?",
                (status, tenant_id))
            self._conn.commit()
        after = self.get_tenant(tenant_id)
        self.audit(actor, f"tenant.{status}", tenant_id, before, after)
        return after

    def suspend(self, tenant_id: str, actor: str) -> dict:
        return self._set_status(tenant_id, STATUS_SUSPENDED, actor)

    def resume(self, tenant_id: str, actor: str) -> dict:
        return self._set_status(tenant_id, STATUS_ACTIVE, actor)

    def set_plan(self, tenant_id: str, plan_id: str, actor: str) -> dict:
        before = self.get_tenant(tenant_id)
        if before is None:
            raise KeyError(tenant_id)
        with self._lock:
            self._conn.execute(
                "UPDATE tenants SET plan_id = ? WHERE id = ?",
                (plan_id, tenant_id))
            self._conn.commit()
        after = self.get_tenant(tenant_id)
        self.audit(actor, "tenant.set_plan", tenant_id, before, after)
        return after

    def delete(self, tenant_id: str, actor: str, archive: bool = True) -> dict:
        """Mark deleted and remove or archive the tenant's DB file per the
        stated retention policy (default: archive the file, keep the record)."""
        before = self.get_tenant(tenant_id)
        if before is None:
            raise KeyError(tenant_id)
        db_path = os.path.join(self._root, tenant_id, "ands.db")
        retention = "removed"
        if os.path.exists(db_path):
            if archive:
                os.makedirs(self._archive, exist_ok=True)
                dest = os.path.join(self._archive, f"{tenant_id}-ands.db")
                shutil.move(db_path, dest)
                retention = "archived"
            else:
                os.remove(db_path)
                retention = "removed"
        after = self._set_status(tenant_id, STATUS_DELETED, actor)
        after = dict(after, retention=retention)
        self.audit(actor, "tenant.delete", tenant_id, before, after)
        return after


class DuplicateTenant(Exception):
    """Raised by ``create_tenant`` when the registration email already maps to a
    tenant — carries the existing tenant so the caller routes to it."""

    def __init__(self, existing: dict):
        super().__init__(f"tenant already exists: {existing['id']}")
        self.existing = existing
