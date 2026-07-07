"""Login must work WITHOUT a tenant_id — users never know tenant UUIDs."""

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app import security
from app.api import build_app
from app.repository_sqlite import SqliteIdentityRepository
from app.service import IdentityService

from tests.conftest import signup_admin


@pytest.fixture
def client():
    repo = SqliteIdentityRepository(SqliteDb(":memory:"))
    svc = IdentityService(repo, InMemoryEventBus()).register()
    return TestClient(build_app(svc))


def _signup(client, email, company, password="Pw-2026!xyz"):
    # full onboarding — round-9: a new workspace requires MFA, so the account
    # comes back with a TOTP secret for password+code logins
    return signup_admin(client, email=email, company=company,
                        password=password)


def test_login_without_tenant_id_finds_tenant_user(client):
    acct = _signup(client, "ra@cro.example", "CRO One")
    r = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "Pw-2026!xyz",
        "mfa_code": security.totp_code(acct["secret"])})
    assert r.status_code == 200
    tok = r.json()["token"]
    me = client.get("/api/identity/auth/me",
                    headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["email"] == "ra@cro.example" and me["tenant_id"]


def test_login_same_email_two_tenants_password_disambiguates(client):
    one = _signup(client, "ra@cro.example", "CRO One")
    # same email in a second tenant with a different password
    two = _signup(client, "ra@cro.example", "CRO Two",
                  password="Other-2026!y")
    a = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "Pw-2026!xyz",
        "mfa_code": security.totp_code(one["secret"])}).json()
    b = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "Other-2026!y",
        "mfa_code": security.totp_code(two["secret"])}).json()
    assert a["user"]["tenant_id"] != b["user"]["tenant_id"]


def test_login_bad_password_still_401(client):
    _signup(client, "ra@cro.example", "CRO One")
    r = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "wrong"})
    assert r.status_code == 401
