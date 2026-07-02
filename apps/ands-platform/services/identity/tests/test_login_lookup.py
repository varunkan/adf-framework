"""Login must work WITHOUT a tenant_id — users never know tenant UUIDs."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteIdentityRepository
from app.service import IdentityService


@pytest.fixture
def client():
    repo = SqliteIdentityRepository(SqliteDb(":memory:"))
    svc = IdentityService(repo, InMemoryEventBus()).register()
    return TestClient(build_app(svc))


def _signup(client, email, company):
    r = client.post("/api/identity/auth/signup", json={
        "email": email, "password": "Pw-2026!xyz", "company_name": company})
    assert r.status_code == 201
    return r.json()


def test_login_without_tenant_id_finds_tenant_user(client):
    _signup(client, "ra@cro.example", "CRO One")
    r = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "Pw-2026!xyz"})
    assert r.status_code == 200
    tok = r.json()["token"]
    me = client.get("/api/identity/auth/me",
                    headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["email"] == "ra@cro.example" and me["tenant_id"]


def test_login_same_email_two_tenants_password_disambiguates(client):
    _signup(client, "ra@cro.example", "CRO One")
    # same email in a second tenant with a different password
    r2 = client.post("/api/identity/auth/signup", json={
        "email": "ra@cro.example", "password": "Other-2026!y",
        "company_name": "CRO Two"})
    assert r2.status_code == 201
    a = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "Pw-2026!xyz"}).json()
    b = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "Other-2026!y"}).json()
    assert a["user"]["tenant_id"] != b["user"]["tenant_id"]


def test_login_bad_password_still_401(client):
    _signup(client, "ra@cro.example", "CRO One")
    r = client.post("/api/identity/auth/login", json={
        "email": "ra@cro.example", "password": "wrong"})
    assert r.status_code == 401
