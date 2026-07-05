"""TIER3-SOD-ENFORCE — port to the identity service's workspace-policy read.

The sign path (``DossierService.record_esign``) consults a tenant's
``require_sod`` to decide whether a signer-is-author e-signature is HARD-BLOCKED.
That policy lives in the identity service; this port fetches it. Every call is
best-effort — an unreachable identity service returns ``None`` and the sign path
degrades to the manifest's own ``enforce_segregation`` flag (advisory), never
crashing. An ``InProcessWorkspacePolicyClient`` wraps a live ``IdentityService``
for the in-process integration mesh + tests.
"""

from __future__ import annotations

from typing import Protocol


class WorkspacePolicyClient(Protocol):
    def workspace_policy(self, tenant_id: str) -> dict | None: ...


class HttpWorkspacePolicyClient:
    def __init__(self, base_url: str) -> None:
        import httpx, os
        tok = os.environ.get("ANDS_INTERNAL_TOKEN", "").strip()
        headers = {"X-Internal-Auth": tok} if tok else {}
        self._c = httpx.Client(base_url=base_url.rstrip("/"), timeout=3.0,
                               headers=headers)

    def workspace_policy(self, tenant_id: str) -> dict | None:
        try:
            r = self._c.get("/api/identity/internal/workspace-policy",
                            params={"tenant_id": tenant_id})
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None


class InProcessWorkspacePolicyClient:
    """Wraps a live ``IdentityService`` — for the integration mesh + tests."""

    def __init__(self, service) -> None:
        self.service = service

    def workspace_policy(self, tenant_id: str) -> dict | None:
        try:
            return self.service.workspace_policy(tenant_id)
        except Exception:
            return None
