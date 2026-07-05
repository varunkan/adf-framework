"""TIER3-SOD-ENFORCE — a per-workspace 'enforce segregation of duties' policy.

An OWNER/tenant-admin can flip a per-tenant ``require_sod`` flag (default OFF).
When it is on, the workspace's stated posture is that an e-signature whose signer
is also an author of the signed content is HARD-BLOCKED (enforced), not merely
warned. This policy is the single source of truth; the sign path (governance +
dossier) reads it and enforces. This module tests ONLY the identity policy
surface — that the flag can be set by an admin (not a plain member), read back on
/tenant/security, and surfaced to the mesh over the internal policy read.

Mirrors the ``require_mfa`` policy pattern (WS4.1) exactly. Honest: this is a
real workspace control over the SIGN path — it is NOT an SSO/IdP identity claim.
"""

from app import rbac

from tests.conftest import auth


def _signup(client, email="ra@acme.io", company="Acme"):
    return client.post("/api/identity/auth/signup",
                       json={"email": email, "password": "pw12345-2026",
                             "company_name": company}).json()


# -- the flag itself ------------------------------------------------------

def test_tenant_admin_can_set_and_read_require_sod(client):
    body = _signup(client)
    tok = body["token"]
    # default is OFF — the honest starting posture (advisory, not enforced)
    sec = client.get("/api/identity/tenant/security", headers=auth(tok)).json()
    assert sec["require_sod"] is False
    # tenant-admin turns it on
    r = client.post("/api/identity/tenant/security/require-sod",
                    json={"require_sod": True}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["require_sod"] is True
    sec2 = client.get("/api/identity/tenant/security", headers=auth(tok)).json()
    assert sec2["require_sod"] is True
    # and it can be turned back off
    r2 = client.post("/api/identity/tenant/security/require-sod",
                     json={"require_sod": False}, headers=auth(tok))
    assert r2.status_code == 200 and r2.json()["require_sod"] is False


def test_plain_user_cannot_set_require_sod(ctx):
    client = ctx.client
    admin = _signup(client)
    tid = admin["tenant"]["id"]
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    login = client.post("/api/identity/auth/login",
                        json={"email": "member@acme.io",
                              "password": "pw12345-2026", "tenant_id": tid}).json()
    r = client.post("/api/identity/tenant/security/require-sod",
                    json={"require_sod": True}, headers=auth(login["token"]))
    assert r.status_code == 403 and r.json()["rule"] == "forbidden"


def test_require_sod_is_independent_of_require_mfa(client):
    """The two workspace policies are orthogonal — turning SoD on must not turn
    MFA on (or vice versa)."""
    tok = _signup(client)["token"]
    client.post("/api/identity/tenant/security/require-sod",
                json={"require_sod": True}, headers=auth(tok))
    sec = client.get("/api/identity/tenant/security", headers=auth(tok)).json()
    assert sec["require_sod"] is True
    assert sec["require_mfa"] is False


# -- the mesh policy read (service-to-service source of truth) -------------

def test_internal_workspace_policy_read_reports_sod(client):
    """The sign path (a backend service) reads the workspace policy for a tenant
    via the internal policy endpoint. In-process (no internal token set) it is
    reachable directly; the payload carries require_sod + require_mfa."""
    body = _signup(client)
    tok = body["token"]
    tid = body["tenant"]["id"]
    client.post("/api/identity/tenant/security/require-sod",
                json={"require_sod": True}, headers=auth(tok))
    pol = client.get(f"/api/identity/internal/workspace-policy?tenant_id={tid}")
    assert pol.status_code == 200
    assert pol.json()["require_sod"] is True
    assert pol.json()["tenant_id"] == tid


def test_internal_workspace_policy_read_unknown_tenant_is_safe_default(client):
    """An unknown tenant must resolve to the safe default (no enforcement) rather
    than error — the sign path degrades to advisory, never to a crash."""
    pol = client.get("/api/identity/internal/workspace-policy?tenant_id=nope")
    assert pol.status_code == 200
    assert pol.json()["require_sod"] is False
