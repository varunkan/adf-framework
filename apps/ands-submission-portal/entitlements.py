#!/usr/bin/env python3
"""Plan + feature-entitlement logic for the multi-tenant control plane.

REQ-080/081/082: the platform owner packages features into named **plans**, each
tenant is assigned exactly one plan, and per-tenant per-feature **overrides** can
explicitly enable/disable a single feature regardless of the plan. A tenant's
EFFECTIVE entitlement for a feature is::

    plan-grants-feature  THEN modified by any explicit per-tenant override

A brand-new tenant is assigned the built-in ``all-features`` plan and has no
disabling overrides, so its effective set is ALL features (REQ-081).

Pure stdlib (sqlite3) — this is platform/control-plane data and lives in the
SEPARATE control-plane database (REQ-078), never inside a tenant's own DB.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from auth import _SqliteStore


# ---------------------------------------------------------------------------
# Feature catalogue — one key per workflow area (mirrors the UI-2 nav). The
# owner toggles these per plan / per tenant; the server enforces them (REQ-082).
# ---------------------------------------------------------------------------

FEATURES: tuple[str, ...] = (
    "dashboard",       # readiness landing (REQ-071)
    "dossiers",        # submissions list + eCTD tree (REQ-072)
    "submit",          # guided new-submission journey (REQ-073)
    "enrolment",       # CO / RT / PI (REQ rep)
    "validation",      # validation engine + integrity gate (REQ-074/075)
    "fees",            # fee calculation
    "esign",           # e-signature
    "transmission",    # CESG package + ESG transmit
    "reviews",         # review & approval workflow (REQ-076)
    "lifecycle",       # post-receipt DSTS lifecycle
    "privacy",         # privacy / PIPEDA controls
    "admin",           # tenant admin (own users + RBAC)
)

FEATURE_LABELS: dict[str, str] = {
    "dashboard": "Dashboard",
    "dossiers": "Submissions & eCTD",
    "submit": "Guided submission",
    "enrolment": "Enrolment (CO/RT/PI)",
    "validation": "Validation",
    "fees": "Fees",
    "esign": "E-signature",
    "transmission": "Transmission",
    "reviews": "Reviews & approvals",
    "lifecycle": "Lifecycle",
    "privacy": "Privacy",
    "admin": "Tenant admin",
}

DEFAULT_PLAN_ID = "all-features"
DEFAULT_PLAN_NAME = "All Features (default)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_features(features) -> list[str]:
    """Keep only known feature keys, de-duplicated, in catalogue order."""
    wanted = set(features or ())
    return [f for f in FEATURES if f in wanted]


class EntitlementStore(_SqliteStore):
    """Plans + per-tenant overrides, persisted to the control-plane DB."""

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS plans (
                       id TEXT PRIMARY KEY,
                       name TEXT UNIQUE NOT NULL,
                       features TEXT NOT NULL,
                       created_at TEXT NOT NULL)""")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS overrides (
                       tenant_id TEXT NOT NULL,
                       feature TEXT NOT NULL,
                       enabled INTEGER NOT NULL,
                       PRIMARY KEY (tenant_id, feature))""")
            self._conn.commit()
            # Seed the built-in default plan that grants EVERY feature (REQ-080).
            row = self._conn.execute(
                "SELECT id FROM plans WHERE id = ?", (DEFAULT_PLAN_ID,)
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO plans (id, name, features, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (DEFAULT_PLAN_ID, DEFAULT_PLAN_NAME,
                     json.dumps(list(FEATURES)), _now()))
                self._conn.commit()

    # -- plans (REQ-080) ----------------------------------------------------
    def _row_to_plan(self, row) -> dict:
        return {"id": row["id"], "name": row["name"],
                "features": json.loads(row["features"]),
                "created_at": row["created_at"]}

    def create_plan(self, name: str, features) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("plan name is required")
        plan_id = name.lower().replace(" ", "-")
        feats = normalize_features(features)
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM plans WHERE id = ? OR name = ?",
                (plan_id, name)).fetchone()
            if exists:
                raise ValueError(f"plan already exists: {name}")
            self._conn.execute(
                "INSERT INTO plans (id, name, features, created_at) "
                "VALUES (?, ?, ?, ?)",
                (plan_id, name, json.dumps(feats), _now()))
            self._conn.commit()
        return {"id": plan_id, "name": name, "features": feats}

    def update_plan(self, plan_id: str, features) -> dict:
        feats = normalize_features(features)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE plans SET features = ? WHERE id = ?",
                (json.dumps(feats), plan_id))
            self._conn.commit()
            if cur.rowcount == 0:
                raise KeyError(plan_id)
        return self.get_plan(plan_id)

    def get_plan(self, plan_id: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return self._row_to_plan(row) if row else None

    def list_plans(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM plans ORDER BY created_at").fetchall()
        return [self._row_to_plan(r) for r in rows]

    # -- overrides (REQ-081) ------------------------------------------------
    def set_override(self, tenant_id: str, feature: str, enabled: bool) -> None:
        if feature not in FEATURES:
            raise ValueError(f"unknown feature: {feature}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO overrides (tenant_id, feature, enabled) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(tenant_id, feature) DO UPDATE SET enabled = ?",
                (tenant_id, feature, 1 if enabled else 0,
                 1 if enabled else 0))
            self._conn.commit()

    def remove_override(self, tenant_id: str, feature: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM overrides WHERE tenant_id = ? AND feature = ?",
                (tenant_id, feature))
            self._conn.commit()

    def list_overrides(self, tenant_id: str) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT feature, enabled FROM overrides WHERE tenant_id = ?",
                (tenant_id,)).fetchall()
        return {r["feature"]: bool(r["enabled"]) for r in rows}

    # -- effective entitlement (REQ-081/082) --------------------------------
    def effective(self, tenant_id: str, plan_id: str) -> dict:
        """Return ``{feature: {"enabled": bool, "source": "plan"|"override"}}``
        for every catalogued feature — the merge of the plan grant and any
        explicit per-tenant override (override wins)."""
        plan = self.get_plan(plan_id) or self.get_plan(DEFAULT_PLAN_ID)
        plan_feats = set(plan["features"]) if plan else set()
        overrides = self.list_overrides(tenant_id)
        result: dict[str, dict] = {}
        for feature in FEATURES:
            if feature in overrides:
                result[feature] = {"enabled": overrides[feature],
                                   "source": "override"}
            else:
                result[feature] = {"enabled": feature in plan_feats,
                                   "source": "plan"}
        return result

    def is_entitled(self, tenant_id: str, plan_id: str, feature: str) -> bool:
        if feature not in FEATURES:
            return False
        return self.effective(tenant_id, plan_id)[feature]["enabled"]

    def entitled_features(self, tenant_id: str, plan_id: str) -> list[str]:
        eff = self.effective(tenant_id, plan_id)
        return [f for f in FEATURES if eff[f]["enabled"]]
