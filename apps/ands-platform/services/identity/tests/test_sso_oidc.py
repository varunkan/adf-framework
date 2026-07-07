"""CAMP-SSO-OIDC — real standards-based SSO/OIDC login.

The #1 production blocker from the task-based usability eval: "the signer is a
typed email, not an authenticated principal — I need real SSO/IdP before this is
our system of record." These tests drive a REAL OIDC Authorization-Code + PKCE
flow in the identity service, exercised end to end against an IN-PROCESS fake
OIDC issuer (its own RS256 signing key + JWKS + token mint) — the SQLite/
in-memory analogue, so no external IdP is needed to prove it.

Covered:
  * the crypto/JWT primitives (RS256 sign+verify, tamper + expiry rejection);
  * the in-process provider's authorize→code→token→id_token round-trip with
    PKCE + nonce binding;
  * per-workspace SSO admin config (enable, issuer/client), admin-gated;
  * SSO login: authorize → callback binds/creates the user to the verified IdP
    subject and mints the existing opaque session;
  * the signer is now an AUTHENTICATED PRINCIPAL — /auth/me reflects the
    SSO-verified issuer/subject; email+password still works (SSO is additive).
"""

import time

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app import jwt_rs256, oidc, security
from app.api import build_app
from app.repository_sqlite import SqliteIdentityRepository
from app.service import IdentityService

from tests.conftest import auth, signup_admin


# ---------------------------------------------------------------------------
# crypto primitives
# ---------------------------------------------------------------------------
def test_rs256_sign_and_verify_roundtrip():
    key = jwt_rs256.generate_rsa_keypair(bits=2048, kid="k1")
    tok = jwt_rs256.encode_id_token(
        {"iss": "https://idp.test", "sub": "u1", "aud": "client",
         "exp": int(time.time()) + 300}, key)
    claims = jwt_rs256.verify_id_token(
        tok, key.jwks(), issuer="https://idp.test", audience="client")
    assert claims["sub"] == "u1"


def test_verify_rejects_tampered_token():
    key = jwt_rs256.generate_rsa_keypair(bits=2048, kid="k1")
    tok = jwt_rs256.encode_id_token(
        {"iss": "i", "sub": "u1", "aud": "c", "exp": int(time.time()) + 300}, key)
    head, payload, sig = tok.split(".")
    forged = jwt_rs256.b64url(
        jwt_rs256.b64url_decode(payload).replace(b"u1", b"u2"))
    with pytest.raises(jwt_rs256.JwtError):
        jwt_rs256.verify_id_token(f"{head}.{forged}.{sig}", key.jwks(),
                                  issuer="i", audience="c")


def test_verify_rejects_expired_and_bad_audience():
    key = jwt_rs256.generate_rsa_keypair(bits=2048, kid="k1")
    tok = jwt_rs256.encode_id_token(
        {"iss": "i", "sub": "u1", "aud": "c", "exp": int(time.time()) - 999}, key)
    with pytest.raises(jwt_rs256.JwtError):
        jwt_rs256.verify_id_token(tok, key.jwks(), issuer="i", audience="c")
    tok2 = jwt_rs256.encode_id_token(
        {"iss": "i", "sub": "u1", "aud": "c", "exp": int(time.time()) + 300}, key)
    with pytest.raises(jwt_rs256.JwtError):
        jwt_rs256.verify_id_token(tok2, key.jwks(), issuer="i",
                                  audience="other")


# ---------------------------------------------------------------------------
# in-process fake issuer (the deterministic test double)
# ---------------------------------------------------------------------------
def test_inprocess_provider_full_roundtrip_with_pkce_and_nonce():
    idp = oidc.InProcessOidcProvider(issuer="https://idp.test/ands")
    idp.register_user("sub-123", "vera@acme.io", "Vera Chen")
    cfg = oidc.OidcClientConfig(issuer=idp.issuer, client_id="ands-client",
                                redirect_uri="https://app/callback")
    req = idp.build_authorization_request(cfg)
    assert "code_challenge=" in req.authorization_url
    assert "code_challenge_method=S256" in req.authorization_url
    code = idp.authorize(req, subject="sub-123", cfg=cfg)
    ident = idp.exchange_code(cfg, code=code, code_verifier=req.code_verifier,
                              nonce=req.nonce)
    assert ident.subject == "sub-123"
    assert ident.email == "vera@acme.io"
    assert ident.name == "Vera Chen"
    assert ident.issuer == "https://idp.test/ands"


def test_inprocess_provider_rejects_bad_pkce_verifier():
    idp = oidc.InProcessOidcProvider()
    idp.register_user("s1", "a@b.io", "A")
    cfg = oidc.OidcClientConfig(issuer=idp.issuer, client_id="c",
                                redirect_uri="https://app/cb")
    req = idp.build_authorization_request(cfg)
    code = idp.authorize(req, subject="s1", cfg=cfg)
    with pytest.raises(jwt_rs256.JwtError):
        idp.exchange_code(cfg, code=code, code_verifier="wrong-verifier",
                          nonce=req.nonce)


def test_inprocess_provider_code_is_single_use():
    idp = oidc.InProcessOidcProvider()
    idp.register_user("s1", "a@b.io", "A")
    cfg = oidc.OidcClientConfig(issuer=idp.issuer, client_id="c",
                                redirect_uri="https://app/cb")
    req = idp.build_authorization_request(cfg)
    code = idp.authorize(req, subject="s1", cfg=cfg)
    idp.exchange_code(cfg, code=code, code_verifier=req.code_verifier,
                      nonce=req.nonce)
    with pytest.raises(jwt_rs256.JwtError):
        idp.exchange_code(cfg, code=code, code_verifier=req.code_verifier,
                          nonce=req.nonce)


# ---------------------------------------------------------------------------
# service / API wiring — SSO-backed workspace
# ---------------------------------------------------------------------------
@pytest.fixture
def sso():
    """An identity service wired with an in-process OIDC provider, an admin
    workspace, and a helper to run the whole login round-trip."""
    repo = SqliteIdentityRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    idp = oidc.InProcessOidcProvider(issuer="https://idp.test/ands")
    service = IdentityService(repo, bus, oidc_provider=idp).register()
    service.ensure_owner("owner@ands.io", "owner-secret")
    client = TestClient(build_app(service))
    # full onboarding (round-9: new workspaces require MFA) → full admin session
    admin = signup_admin(client, email="admin@acme.io", company="Acme")
    return {"client": client, "service": service, "repo": repo, "idp": idp,
            "admin_token": admin["token"], "tenant_id": admin["tenant"]["id"]}


def _configure_sso(sso, *, client_id="ands-client",
                   issuer="https://idp.test/ands"):
    r = sso["client"].post(
        "/api/identity/tenant/sso",
        json={"enabled": True, "issuer": issuer, "client_id": client_id,
              "client_secret": "shh"},
        headers=auth(sso["admin_token"]))
    assert r.status_code == 200, r.text
    return r.json()


def test_sso_config_is_admin_gated(sso):
    """A plain member cannot configure workspace SSO."""
    from app import rbac
    sso["service"]._add_user(sso["tenant_id"], "member@acme.io",
                             "pw12345-2026", rbac.USER_ROLE, "Member")
    # the workspace requires MFA by default (round-9): the member enrols via
    # the blocked-login setup token, then signs in with password + TOTP
    blocked = sso["client"].post(
        "/api/identity/auth/login",
        json={"email": "member@acme.io", "password": "pw12345-2026",
              "tenant_id": sso["tenant_id"]})
    assert blocked.status_code == 403
    setup = blocked.json()["setup_token"]
    enrol = sso["client"].post("/api/identity/auth/mfa/enroll",
                               headers=auth(setup)).json()
    sso["client"].post("/api/identity/auth/mfa/verify",
                       json={"code": security.totp_code(enrol["secret"])},
                       headers=auth(setup))
    login = sso["client"].post(
        "/api/identity/auth/login",
        json={"email": "member@acme.io", "password": "pw12345-2026",
              "tenant_id": sso["tenant_id"],
              "mfa_code": security.totp_code(enrol["secret"])}).json()
    r = sso["client"].post(
        "/api/identity/tenant/sso",
        json={"enabled": True, "issuer": "https://idp.test/ands",
              "client_id": "c"},
        headers=auth(login["token"]))
    assert r.status_code == 403


def test_sso_config_roundtrips_and_hides_secret(sso):
    _configure_sso(sso)
    cfg = sso["client"].get("/api/identity/tenant/sso",
                            headers=auth(sso["admin_token"])).json()
    assert cfg["enabled"] is True
    assert cfg["issuer"] == "https://idp.test/ands"
    assert cfg["client_id"] == "ands-client"
    # the secret must never be echoed back to the browser
    assert "client_secret" not in cfg or not cfg.get("client_secret")
    assert cfg.get("configured") is True


def test_sso_login_binds_verified_principal_and_mints_session(sso):
    _configure_sso(sso)
    sso["idp"].register_user("idp-sub-9", "signer@acme.io", "Signed Signer")
    # 1) begin: the app asks identity for the authorization redirect
    begin = sso["client"].post(
        "/api/identity/auth/sso/authorize",
        json={"tenant_id": sso["tenant_id"],
              "redirect_uri": "https://app/callback"}).json()
    assert "authorization_url" in begin and begin["state"]
    # 2) the user consents at the (in-process) IdP → we get a code back
    req = oidc.AuthorizationRequest(
        authorization_url=begin["authorization_url"], state=begin["state"],
        nonce=begin["_nonce"], code_verifier=begin["_code_verifier"])
    cfg = oidc.OidcClientConfig(issuer="https://idp.test/ands",
                                client_id="ands-client",
                                redirect_uri="https://app/callback")
    code = sso["idp"].authorize(req, subject="idp-sub-9", cfg=cfg)
    # 3) callback: identity validates the token, binds the user, mints a session
    cb = sso["client"].post("/api/identity/auth/sso/callback",
                            json={"state": begin["state"], "code": code}).json()
    assert cb["token"]
    assert cb["user"]["email"] == "signer@acme.io"
    assert cb["user"]["tenant_id"] == sso["tenant_id"]
    # 4) the session resolves and /auth/me reflects an SSO-VERIFIED principal
    me = sso["client"].get("/api/identity/auth/me",
                           headers=auth(cb["token"])).json()
    assert me["email"] == "signer@acme.io"
    assert me["identity_verified"] is True
    assert me["identity_issuer"] == "https://idp.test/ands"
    assert me["identity_subject"] == "idp-sub-9"


def test_password_login_still_works_and_is_recorded_email(sso):
    """SSO is additive — the email+password principal is unchanged and is
    honestly a recorded email (not SSO-verified)."""
    me = sso["client"].get("/api/identity/auth/me",
                           headers=auth(sso["admin_token"])).json()
    assert me["email"] == "admin@acme.io"
    assert me["identity_verified"] is False


def test_sso_callback_rejects_unknown_state(sso):
    _configure_sso(sso)
    r = sso["client"].post("/api/identity/auth/sso/callback",
                           json={"state": "nope", "code": "whatever"})
    assert r.status_code in (400, 401, 422)


def test_sso_authorize_refused_when_workspace_has_no_sso(sso):
    """A workspace that never enabled SSO cannot start the OIDC flow."""
    r = sso["client"].post(
        "/api/identity/auth/sso/authorize",
        json={"tenant_id": sso["tenant_id"],
              "redirect_uri": "https://app/callback"})
    assert r.status_code in (400, 404, 422)
