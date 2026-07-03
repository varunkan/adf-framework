"""Role-based access control — pure authorize() (ported/simplified from monolith).

Hard tenant isolation + least-privilege capability check. A non-owner can never
act on another tenant's resource (REQ-083); each role grants a capability set.
"""

from __future__ import annotations

OWNER_ROLE = "owner"
TENANT_ADMIN_ROLE = "tenant-admin"
USER_ROLE = "user"
ROLES = (OWNER_ROLE, TENANT_ADMIN_ROLE, USER_ROLE)

# capability sets per role (owner is unconditional, handled below)
_USER_CAPS = {"tenant.read", "dossier.read", "dossier.write", "validate"}
_TENANT_ADMIN_CAPS = _USER_CAPS | {"tenant.manage_users", "admin", "transmit",
                                   "billing.read"}
_ROLE_CAPS = {
    USER_ROLE: _USER_CAPS,
    TENANT_ADMIN_ROLE: _TENANT_ADMIN_CAPS,
}


def capabilities_for(role: str) -> set:
    if role == OWNER_ROLE:
        return {"*"}
    return set(_ROLE_CAPS.get(role, set()))


# human-readable gloss + who may grant each role (surfaced in the Account-page
# matrix; the *capability* column below is sourced from capabilities_for so the
# UI can never drift from what authorize() enforces).
_ROLE_LABELS = {
    OWNER_ROLE: "Platform owner",
    TENANT_ADMIN_ROLE: "Workspace admin",
    USER_ROLE: "Member",
}
_ROLE_SUMMARIES = {
    OWNER_ROLE: ("Runs the control plane across every workspace: provisioning "
                 "tenants, plans, entitlements and billing. Not a per-workspace "
                 "role."),
    TENANT_ADMIN_ROLE: ("Full authority inside one workspace — manages members, "
                        "signs and transmits filings, and reads billing."),
    USER_ROLE: ("Day-to-day contributor — reads and writes dossiers and runs "
                "validation inside this workspace."),
}
_ROLE_ASSIGNABLE_BY = {
    OWNER_ROLE: "Bootstrapped at deploy time; not assignable from the app.",
    TENANT_ADMIN_ROLE: "Assigned by the platform owner when a workspace is "
                       "provisioned.",
    USER_ROLE: "Invited by a workspace admin (tenant.manage_users).",
}
# stable, human-facing order for the capabilities enforced by authorize()
_CAP_ORDER = ("tenant.read", "dossier.read", "dossier.write", "validate",
              "tenant.manage_users", "admin", "transmit", "billing.read")


def _ordered_caps(role: str) -> list[str]:
    caps = capabilities_for(role)
    if caps == {"*"}:
        return ["*"]
    ordered = [c for c in _CAP_ORDER if c in caps]
    ordered += sorted(c for c in caps if c not in _CAP_ORDER)
    return ordered


def role_matrix() -> list[dict]:
    """The permission matrix for every role, capabilities sourced live from
    capabilities_for() so it stays lock-step with enforcement."""
    return [{
        "role": role,
        "label": _ROLE_LABELS.get(role, role),
        "summary": _ROLE_SUMMARIES.get(role, ""),
        "capabilities": _ordered_caps(role),
        "assignable_by": _ROLE_ASSIGNABLE_BY.get(role, ""),
    } for role in ROLES]


def authorize(principal: dict, capability: str, resource: dict | None = None) -> dict:
    """Return ``{"allowed": bool, "rule": str}`` for a principal acting on a
    resource. Owner is platform-wide; everyone else is tenant-isolated."""
    principal = principal or {}
    resource = resource or {}
    role = str(principal.get("role") or "")
    p_tenant = str(principal.get("tenant_id") or "")
    r_tenant = str(resource.get("tenant_id") or "")

    if role == OWNER_ROLE:
        return {"allowed": True, "rule": "owner_platform_scope"}

    if r_tenant and r_tenant != p_tenant:
        return {"allowed": False, "rule": "cross_tenant_denied"}

    if capability in capabilities_for(role):
        return {"allowed": True, "rule": "capability_granted"}
    return {"allowed": False, "rule": "insufficient_capability"}
