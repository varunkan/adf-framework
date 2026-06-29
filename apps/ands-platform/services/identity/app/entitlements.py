"""Feature entitlements — pure merge of plan grants + per-tenant overrides.

Ported from the monolith ``entitlements``. Effective = plan-grants-feature THEN
modified by any explicit per-tenant override (override wins). REQ-080/081/082.
"""

from __future__ import annotations

FEATURES = (
    "dashboard", "dossiers", "submit", "enrolment", "validation", "fees",
    "esign", "transmission", "reviews", "lifecycle", "privacy", "admin",
)

DEFAULT_PLAN_ID = "all-features"
DEFAULT_PLAN_NAME = "All Features (default)"


def normalize_features(features) -> list:
    """Keep only known feature keys, de-duplicated, in catalogue order."""
    wanted = set(features or ())
    return [f for f in FEATURES if f in wanted]


def plan_id_from_name(name: str) -> str:
    return str(name or "").strip().lower().replace(" ", "-")


def effective(plan_features, overrides: dict) -> dict:
    """``{feature: {"enabled": bool, "source": "plan"|"override"}}`` for every
    catalogued feature (override wins over the plan grant)."""
    plan_feats = set(plan_features or ())
    overrides = overrides or {}
    result = {}
    for feature in FEATURES:
        if feature in overrides:
            result[feature] = {"enabled": bool(overrides[feature]),
                               "source": "override"}
        else:
            result[feature] = {"enabled": feature in plan_feats,
                               "source": "plan"}
    return result


def entitled_features(plan_features, overrides: dict) -> list:
    eff = effective(plan_features, overrides)
    return [f for f in FEATURES if eff[f]["enabled"]]
