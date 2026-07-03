"""WS4.1 — workspace-mandated MFA.

An OWNER/tenant-admin can flip a per-tenant 'require MFA for all members' flag.
Once set, password-only sign-in for that workspace is BLOCKED server-side until
the member enrols + verifies TOTP. This does not weaken the existing per-user
MFA path (a user who has MFA on still gets the mfa_required challenge).
"""

from app import rbac, security

from tests.conftest import auth, owner_token


def _signup(client, email="ra@acme.io", company="Acme"):
    return client.post("/api/identity/auth/signup",
                       json={"email": email, "password": "pw12345-2026",
                             "company_name": company}).json()


def _enable_mfa(client, token):
    enrol = client.post("/api/identity/auth/mfa/enroll",
                        headers=auth(token)).json()
    client.post("/api/identity/auth/mfa/verify",
                json={"code": security.totp_code(enrol["secret"])},
                headers=auth(token))
    return enrol["secret"]


# -- the flag itself ------------------------------------------------------

def test_tenant_admin_can_set_and_read_require_mfa(client):
    body = _signup(client)
    tok = body["token"]
    # default is off
    sec = client.get("/api/identity/tenant/security", headers=auth(tok)).json()
    assert sec["require_mfa"] is False
    # the admin enrols MFA first — the mandate is airtight and applies to the
    # admin too, so an admin without MFA would lock its own session out.
    _enable_mfa(client, tok)
    # tenant-admin turns it on
    r = client.post("/api/identity/tenant/security/require-mfa",
                    json={"require_mfa": True}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["require_mfa"] is True
    sec2 = client.get("/api/identity/tenant/security", headers=auth(tok)).json()
    assert sec2["require_mfa"] is True


def test_plain_user_cannot_set_require_mfa(ctx):
    client = ctx.client
    admin = _signup(client)
    # provision a plain USER in the same tenant via the service seam
    tid = admin["tenant"]["id"]
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    login = client.post("/api/identity/auth/login",
                        json={"email": "member@acme.io",
                              "password": "pw12345-2026", "tenant_id": tid}).json()
    r = client.post("/api/identity/tenant/security/require-mfa",
                    json={"require_mfa": True}, headers=auth(login["token"]))
    assert r.status_code == 403 and r.json()["rule"] == "forbidden"


# -- enforcement (the security-critical part) -----------------------------

def test_login_blocked_when_workspace_requires_mfa_and_member_has_none(ctx):
    client = ctx.client
    admin = _signup(client)
    tid = admin["tenant"]["id"]
    # admin turns the workspace mandate on
    client.post("/api/identity/tenant/security/require-mfa",
                json={"require_mfa": True}, headers=auth(admin["token"]))
    # a member with NO MFA is added
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    # correct password alone must NOT mint a session
    r = client.post("/api/identity/auth/login",
                    json={"email": "member@acme.io", "password": "pw12345-2026",
                          "tenant_id": tid})
    assert r.status_code == 403
    assert r.json()["rule"] == "workspace_mfa_required"
    assert "token" not in r.json()


def test_member_can_enrol_via_setup_token_then_login(ctx):
    """The blocked member still gets a path: a short-lived setup token is
    returned so they can enrol MFA, after which login succeeds."""
    client = ctx.client
    admin = _signup(client)
    tid = admin["tenant"]["id"]
    client.post("/api/identity/tenant/security/require-mfa",
                json={"require_mfa": True}, headers=auth(admin["token"]))
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    blocked = client.post("/api/identity/auth/login",
                          json={"email": "member@acme.io",
                                "password": "pw12345-2026", "tenant_id": tid})
    setup_token = blocked.json()["setup_token"]
    assert setup_token
    # the setup token authorises MFA enrolment only
    enrol = _enable_mfa(client, setup_token)
    # now a full login with the code works
    ok = client.post("/api/identity/auth/login",
                     json={"email": "member@acme.io", "password": "pw12345-2026",
                           "tenant_id": tid,
                           "mfa_code": security.totp_code(enrol)})
    assert ok.status_code == 200 and ok.json()["token"]


def test_workspace_mandate_does_not_break_member_with_mfa(ctx):
    client = ctx.client
    admin = _signup(client)
    tid = admin["tenant"]["id"]
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    login = client.post("/api/identity/auth/login",
                        json={"email": "member@acme.io",
                              "password": "pw12345-2026", "tenant_id": tid}).json()
    secret = _enable_mfa(client, login["token"])
    client.post("/api/identity/tenant/security/require-mfa",
                json={"require_mfa": True}, headers=auth(admin["token"]))
    # member has MFA — the normal mfa_required challenge still governs
    no_code = client.post("/api/identity/auth/login",
                          json={"email": "member@acme.io",
                                "password": "pw12345-2026", "tenant_id": tid})
    assert no_code.status_code == 401 and no_code.json()["rule"] == "mfa_required"
    ok = client.post("/api/identity/auth/login",
                     json={"email": "member@acme.io", "password": "pw12345-2026",
                           "tenant_id": tid, "mfa_code": security.totp_code(secret)})
    assert ok.status_code == 200


def test_require_mfa_flag_survives_owner_scope(ctx):
    """A platform owner (no tenant) never gets locked out by a tenant mandate."""
    client = ctx.client
    tok = owner_token(ctx)
    me = client.get("/api/identity/auth/me", headers=auth(tok)).json()
    assert me["role"] == rbac.OWNER_ROLE
    # owner login continues to work (no tenant mandate applies)
    r = client.post("/api/identity/auth/login",
                    json={"email": ctx.owner_email, "password": ctx.owner_pw})
    assert r.status_code == 200


# -- ADVERSARIAL REVIEW EXPLOITS (WS4 security fix) -----------------------
# These are the two proven holes; each fails RED before the fix and is GREEN
# after. A mandate that can be bypassed is worse than none, so they are the
# acceptance gate.

def _blocked_setup_token(ctx):
    """Turn the mandate on (admin has MFA) then return a fresh member's
    scope='mfa_setup' token from the login block-branch."""
    client = ctx.client
    admin = _signup(client)
    tid = admin["tenant"]["id"]
    _enable_mfa(client, admin["token"])
    client.post("/api/identity/tenant/security/require-mfa",
                json={"require_mfa": True}, headers=auth(admin["token"]))
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    blocked = client.post("/api/identity/auth/login",
                          json={"email": "member@acme.io",
                                "password": "pw12345-2026", "tenant_id": tid})
    assert blocked.status_code == 403
    assert blocked.json()["rule"] == "workspace_mfa_required"
    return ctx, tid, blocked.json()["setup_token"]


def test_setup_token_cannot_reach_protected_endpoints_but_can_enrol(ctx):
    """Hole #1 (CRITICAL): the login-block setup token must NOT be a full
    session. It is rejected by /auth/me, /tenant/security and /rbac/matrix,
    yet still works for /auth/mfa/enroll + /auth/mfa/verify."""
    ctx, tid, setup = _blocked_setup_token(ctx)
    client = ctx.client

    # (a) protected endpoints reject the setup token
    for path in ("/api/identity/auth/me", "/api/identity/tenant/security",
                 "/api/identity/rbac/matrix"):
        r = client.get(path, headers=auth(setup))
        assert r.status_code in (401, 403), (path, r.status_code)
        assert r.json().get("rule") in ("mfa_setup_scope",
                                        "workspace_mfa_required", "no_session")

    # (b) but the enrolment path DOES accept it
    enrol = client.post("/api/identity/auth/mfa/enroll", headers=auth(setup))
    assert enrol.status_code == 200 and enrol.json()["secret"]
    v = client.post("/api/identity/auth/mfa/verify",
                    json={"code": security.totp_code(enrol.json()["secret"])},
                    headers=auth(setup))
    assert v.status_code == 200 and v.json()["enabled"] is True

    # (c) after enrol+verify a normal login yields a real, full session
    ok = client.post("/api/identity/auth/login",
                     json={"email": "member@acme.io", "password": "pw12345-2026",
                           "tenant_id": tid,
                           "mfa_code": security.totp_code(enrol.json()["secret"])})
    assert ok.status_code == 200 and ok.json()["token"]
    me = client.get("/api/identity/auth/me", headers=auth(ok.json()["token"]))
    assert me.status_code == 200 and me.json()["email"] == "member@acme.io"


def test_preexisting_full_session_dies_when_mandate_turned_on(ctx):
    """Hole #2 (HIGH): a full session minted BEFORE the mandate is turned on
    must STOP working the moment it is on, for a member without MFA — while a
    member WITH verified MFA is unaffected."""
    client = ctx.client
    admin = _signup(client)
    tid = admin["tenant"]["id"]
    _enable_mfa(client, admin["token"])

    # a member with NO MFA logs in NORMALLY (mandate still off) -> full session
    ctx.service._add_user(tid, "nomfa@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "NoMfa")
    nomfa_tok = client.post("/api/identity/auth/login",
                            json={"email": "nomfa@acme.io",
                                  "password": "pw12345-2026",
                                  "tenant_id": tid}).json()["token"]
    # a member WITH MFA also has a live full session
    ctx.service._add_user(tid, "hasmfa@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "HasMfa")
    hasmfa_login = client.post("/api/identity/auth/login",
                               json={"email": "hasmfa@acme.io",
                                     "password": "pw12345-2026",
                                     "tenant_id": tid}).json()
    hasmfa_secret = _enable_mfa(client, hasmfa_login["token"])
    hasmfa_tok = client.post(
        "/api/identity/auth/login",
        json={"email": "hasmfa@acme.io", "password": "pw12345-2026",
              "tenant_id": tid,
              "mfa_code": security.totp_code(hasmfa_secret)}).json()["token"]

    # both sessions work while the mandate is off
    assert client.get("/api/identity/auth/me",
                      headers=auth(nomfa_tok)).status_code == 200
    assert client.get("/api/identity/auth/me",
                      headers=auth(hasmfa_tok)).status_code == 200

    # admin flips the mandate ON
    client.post("/api/identity/tenant/security/require-mfa",
                json={"require_mfa": True}, headers=auth(admin["token"]))

    # the no-MFA member's PRE-EXISTING session is now dead: revoke-on-mandate-on
    # deleted it, so /auth/me is 401 no_session (a hard lockout either way).
    dead = client.get("/api/identity/auth/me", headers=auth(nomfa_tok))
    assert dead.status_code in (401, 403)
    assert dead.json()["rule"] in ("no_session", "workspace_mfa_required")

    # the MFA-enrolled member is unaffected
    assert client.get("/api/identity/auth/me",
                      headers=auth(hasmfa_tok)).status_code == 200


def test_resolve_backstop_blocks_nonmfa_session_even_without_revoke(ctx):
    """The resolve() check is the DURABLE backstop: even if a full session
    survives (revoke skipped), it must be rejected 403 the instant the mandate
    is on. We flip the tenant flag directly at the repo so no revoke runs."""
    client = ctx.client
    admin = _signup(client)
    tid = admin["tenant"]["id"]
    ctx.service._add_user(tid, "member@acme.io", "pw12345-2026",
                          rbac.USER_ROLE, "Member")
    tok = client.post("/api/identity/auth/login",
                      json={"email": "member@acme.io", "password": "pw12345-2026",
                            "tenant_id": tid}).json()["token"]
    assert client.get("/api/identity/auth/me",
                      headers=auth(tok)).status_code == 200
    # turn the mandate on at the persistence layer ONLY (bypasses the service
    # revoke) so the pre-existing full session is still present
    ctx.repo.set_require_mfa(tid, True)
    r = client.get("/api/identity/auth/me", headers=auth(tok))
    assert r.status_code == 403 and r.json()["rule"] == "workspace_mfa_required"


def test_setup_token_can_logout(ctx):
    """/auth/logout must accept a setup token (a blocked member may abandon)."""
    ctx, _tid, setup = _blocked_setup_token(ctx)
    r = ctx.client.post("/api/identity/auth/logout", headers=auth(setup))
    assert r.status_code == 200 and r.json()["ok"] is True
    # token is now gone — enrolment no longer works with it
    assert ctx.client.post("/api/identity/auth/mfa/enroll",
                           headers=auth(setup)).status_code == 401
