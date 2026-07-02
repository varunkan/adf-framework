"""F1 / SAAS-NFR-003 — TOTP MFA enrol, verify, and login enforcement."""

from app import security

from tests.conftest import auth


def test_totp_roundtrip_and_skew_window():
    secret = security.new_totp_secret()
    at = 1_700_000_000
    code = security.totp_code(secret, at)
    assert security.verify_totp(secret, code, at)
    assert security.verify_totp(secret, code, at + 25)        # within step
    assert not security.verify_totp(secret, "000000", at)
    assert security.provisioning_uri(secret, "a@b.io").startswith("otpauth://")


def _signup_token(client, email="ra@acme.io"):
    return client.post("/api/identity/auth/signup",
                       json={"email": email, "password": "pw12345-2026",
                             "company_name": "Acme"}).json()


def test_enroll_then_verify_enables_mfa(client):
    body = _signup_token(client)
    enrol = client.post("/api/identity/auth/mfa/enroll",
                        headers=auth(body["token"])).json()
    assert enrol["enabled"] is False and enrol["secret"]
    code = security.totp_code(enrol["secret"])
    v = client.post("/api/identity/auth/mfa/verify", json={"code": code},
                    headers=auth(body["token"]))
    assert v.status_code == 200 and v.json()["enabled"] is True
    status = client.get("/api/identity/auth/mfa/status",
                        headers=auth(body["token"])).json()
    assert status["enabled"] is True


def test_login_requires_mfa_once_enabled(client):
    body = _signup_token(client)
    tenant_id = body["tenant"]["id"]
    enrol = client.post("/api/identity/auth/mfa/enroll",
                        headers=auth(body["token"])).json()
    client.post("/api/identity/auth/mfa/verify",
                json={"code": security.totp_code(enrol["secret"])},
                headers=auth(body["token"]))
    # login without a code is now rejected
    no_code = client.post("/api/identity/auth/login",
                          json={"email": "ra@acme.io", "password": "pw12345-2026",
                                "tenant_id": tenant_id})
    assert no_code.status_code == 401 and no_code.json()["rule"] == "mfa_required"
    # login with a valid code succeeds
    ok = client.post("/api/identity/auth/login",
                     json={"email": "ra@acme.io", "password": "pw12345-2026",
                           "tenant_id": tenant_id,
                           "mfa_code": security.totp_code(enrol["secret"])})
    assert ok.status_code == 200 and ok.json()["token"]


def test_verify_without_enrol_422(client):
    body = _signup_token(client)
    r = client.post("/api/identity/auth/mfa/verify", json={"code": "123456"},
                    headers=auth(body["token"]))
    assert r.status_code == 422
