"""Round-9 onboarding item 4 (BLOCKER, n=4) — the workspace MFA policy defaults
to 'Required' (enforced at sign-in for every member) for NEW workspaces, with
relaxation an explicit admin action.

Design (honest + non-destructive):
- ``create_tenant`` inserts ``require_mfa=1`` for newly created workspaces
  (self-serve signup AND owner provisioning). The DDL default stays 0 so
  PRE-EXISTING workspaces are not silently flipped into a lockout.
- ``signup`` therefore cannot mint a full session for the founding admin (they
  have no MFA yet) — it returns a setup-scoped token plus
  ``mfa_setup_required: True`` so the UI can guide authenticator setup.
"""

from app import rbac, security

from tests.conftest import auth, owner_token, signup_admin


def _enrol_and_verify(client, token) -> str:
    enrol = client.post("/api/identity/auth/mfa/enroll",
                        headers=auth(token)).json()
    v = client.post("/api/identity/auth/mfa/verify",
                    json={"code": security.totp_code(enrol["secret"])},
                    headers=auth(token))
    assert v.status_code == 200, v.text
    return enrol["secret"]


# 1 — signup flags the guided setup and its token is setup-scoped only
def test_signup_returns_mfa_setup_flag_and_setup_scoped_token(client):
    r = client.post("/api/identity/auth/signup",
                    json={"email": "ra@acme.io", "password": "pw12345-2026",
                          "company_name": "Acme"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mfa_setup_required"] is True
    assert body["token"]
    # the token must NOT be a full session in disguise
    me = client.get("/api/identity/auth/me", headers=auth(body["token"]))
    assert me.status_code in (401, 403)
    assert me.json()["rule"] == "mfa_setup_scope"


# 2 — the full onboarding path lands on an enforced Required default
def test_full_onboarding_path_shows_require_mfa_default_on(client):
    admin = signup_admin(client)
    sec = client.get("/api/identity/tenant/security",
                     headers=auth(admin["token"])).json()
    assert sec["require_mfa"] is True


# 3 — a member of a fresh workspace cannot sign in password-only, with no
#     explicit admin action ever taken
def test_fresh_workspace_member_blocked_password_only(ctx):
    client = ctx.client
    admin = signup_admin(client)
    tid = admin["tenant"]["id"]
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    r = client.post("/api/identity/auth/login",
                    json={"email": "member@acme.io", "password": "pw12345-2026",
                          "tenant_id": tid})
    assert r.status_code == 403
    assert r.json()["rule"] == "workspace_mfa_required"
    assert "token" not in r.json()


# 4 — relaxation is an explicit admin action
def test_relaxation_is_explicit_admin_action(ctx):
    client = ctx.client
    admin = signup_admin(client)
    tid = admin["tenant"]["id"]
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    r = client.post("/api/identity/tenant/security/require-mfa",
                    json={"require_mfa": False}, headers=auth(admin["token"]))
    assert r.status_code == 200 and r.json()["require_mfa"] is False
    ok = client.post("/api/identity/auth/login",
                     json={"email": "member@acme.io",
                           "password": "pw12345-2026", "tenant_id": tid})
    assert ok.status_code == 200 and ok.json()["token"]


# 5 — owner-provisioned tenants also default to Required
def test_owner_provisioned_tenant_defaults_required(ctx):
    client = ctx.client
    tok = owner_token(ctx)
    r = client.post("/api/identity/owner/tenants",
                    json={"name": "BigPharma", "admin_email": "admin@big.io",
                          "admin_password": "pw12345-2026"},
                    headers=auth(tok))
    assert r.status_code == 201, r.text
    tid = r.json()["tenant"]["id"]
    # first password login is blocked with a setup token — the existing
    # login-block → setup path carries the provisioned admin through enrolment
    blocked = client.post("/api/identity/auth/login",
                          json={"email": "admin@big.io",
                                "password": "pw12345-2026", "tenant_id": tid})
    assert blocked.status_code == 403
    assert blocked.json()["rule"] == "workspace_mfa_required"
    secret = _enrol_and_verify(client, blocked.json()["setup_token"])
    ok = client.post("/api/identity/auth/login",
                     json={"email": "admin@big.io", "password": "pw12345-2026",
                           "tenant_id": tid,
                           "mfa_code": security.totp_code(secret)})
    assert ok.status_code == 200 and ok.json()["token"]
