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
