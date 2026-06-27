#!/usr/bin/env python3
"""Application-shell navigation map (REQ-085 / UI-1).

The market-leading regulatory-submission tools (Veeva Vault Submissions,
LORENZ docuBridge) are multi-page, tabbed workspaces where every workflow area
lives on its OWN deep-linkable page — not a single scrolling form-wall. This
module is the single source of truth for that route map so the server (which
serves the shell + filters by entitlement) and the client router (which renders
the active page, breadcrumbs and active-nav state) agree on it.

Two shells share one route vocabulary but are NEVER mixed (UI-1):

* the **tenant workspace** — one entry per entitled workflow feature, and
* the **owner control plane** — the platform-owner-only pages (REQ-079).

The tenant nav keys are exactly the entitlement feature keys
(:data:`entitlements.FEATURES`) so a feature the tenant is not entitled to
simply never renders a nav entry (REQ-082) — there is no second list to keep in
sync. Pure stdlib; the shape is plain dicts/lists ready for ``json.dumps``.
"""

from __future__ import annotations

import entitlements as _ent


# Workspace landing — every breadcrumb trail starts here (UI-1).
WORKSPACE_HOME = {"label": "Workspace", "route": "/dashboard"}

# Ordered tenant workspace nav: one item per workflow area. ``feature`` ties the
# entry to its entitlement key; ``icon`` is a self-contained glyph (no CDN); the
# router uses ``route`` for History-API navigation and ``breadcrumb`` for the
# location trail. Order mirrors entitlements.FEATURES so the rail reads top→down
# in the natural submission flow.
TENANT_NAV: tuple[dict, ...] = (
    {"feature": "dashboard",    "route": "/dashboard",    "icon": "◧"},
    {"feature": "dossiers",     "route": "/dossiers",     "icon": "▤"},
    {"feature": "submit",       "route": "/submit",       "icon": "✚"},
    {"feature": "enrolment",    "route": "/enrolment",    "icon": "⛿"},
    {"feature": "validation",   "route": "/validation",   "icon": "✓"},
    {"feature": "fees",         "route": "/fees",         "icon": "$"},
    {"feature": "esign",        "route": "/esign",        "icon": "✍"},
    {"feature": "transmission", "route": "/transmission", "icon": "➤"},
    {"feature": "reviews",      "route": "/reviews",      "icon": "☑"},
    {"feature": "lifecycle",    "route": "/lifecycle",    "icon": "↻"},
    {"feature": "privacy",      "route": "/privacy",      "icon": "⚿"},
    {"feature": "admin",        "route": "/admin",        "icon": "⚙"},
)

# Deep-linkable detail routes that hang off a list page (UI-2). They carry no
# top-level nav entry but MUST serve the shell so a refresh/bookmark works; the
# router resolves them to their parent's active-nav + an extra breadcrumb.
TENANT_DETAIL_PREFIXES: tuple[tuple[str, str], ...] = (
    # (prefix, parent feature)
    ("/dossiers/", "dossiers"),
)

# Owner control-plane nav — a SEPARATE shell (REQ-079). Tenant-detail hangs off
# the Tenants list as a deep-linkable drill-in.
OWNER_NAV: tuple[dict, ...] = (
    {"key": "tenants", "route": "/owner",       "label": "Tenants",
     "icon": "▤"},
    {"key": "plans",   "route": "/owner/plans", "label": "Plans",
     "icon": "◳"},
)

OWNER_DETAIL_PREFIXES: tuple[str, ...] = ("/owner/tenants/",)


def _label(feature: str) -> str:
    return _ent.FEATURE_LABELS.get(feature, feature.title())


def tenant_nav(entitled_features) -> list[dict]:
    """The workspace nav, filtered to the tenant's entitled features (REQ-082).

    Only entitled areas render an entry; the rest are hidden in the UI (and
    still 403 at the API). Each entry is enriched with its human label and the
    breadcrumb trail the router shows when that page is active.
    """
    allowed = set(entitled_features or ())
    out: list[dict] = []
    for item in TENANT_NAV:
        feat = item["feature"]
        if feat not in allowed:
            continue
        label = _label(feat)
        out.append({
            "feature": feat,
            "route": item["route"],
            "label": label,
            "icon": item["icon"],
            "breadcrumb": [WORKSPACE_HOME["label"], label],
        })
    return out


def owner_nav() -> list[dict]:
    """The owner control-plane nav (always the full set for the owner)."""
    return [dict(item, breadcrumb=["Control plane", item["label"]])
            for item in OWNER_NAV]


def all_tenant_routes() -> list[str]:
    """Every concrete top-level workspace route (no detail prefixes)."""
    return [item["route"] for item in TENANT_NAV]


def resolve_tenant_route(path: str):
    """Map a workspace URL path to ``(feature, detail_id)`` or ``None``.

    Returns ``(feature, None)`` for a top-level page, ``(feature, "<id>")`` for
    a deep-linkable detail page, or ``None`` when the path is not a workspace
    route — so the server knows whether to serve the shell and the router knows
    which nav entry to mark active.
    """
    path = (path or "").rstrip("/")
    if not path:
        # bare "/" is the legacy single page, NOT a workspace route.
        return None
    for item in TENANT_NAV:
        if path == item["route"]:
            return (item["feature"], None)
    for prefix, feature in TENANT_DETAIL_PREFIXES:
        if path.startswith(prefix) and len(path) > len(prefix):
            return (feature, path[len(prefix):])
    return None


def is_owner_route(path: str) -> bool:
    """True for any owner control-plane page (top-level or detail drill-in)."""
    path = (path or "").rstrip("/") or "/owner"
    if path in {item["route"].rstrip("/") or "/owner" for item in OWNER_NAV}:
        return True
    return any(path.startswith(p) and len(path) > len(p)
               for p in OWNER_DETAIL_PREFIXES)
