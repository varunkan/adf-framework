"""Shared fixtures — a fresh in-memory identity service (with an owner) per test."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteIdentityRepository
from app.service import IdentityService

OWNER_EMAIL = "owner@ands.io"
OWNER_PW = "owner-secret"


@pytest.fixture
def ctx():
    repo = SqliteIdentityRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    service = IdentityService(repo, bus).register()
    service.ensure_owner(OWNER_EMAIL, OWNER_PW)
    client = TestClient(build_app(service))
    return SimpleNamespace(client=client, service=service, bus=bus, repo=repo,
                           owner_email=OWNER_EMAIL, owner_pw=OWNER_PW)


@pytest.fixture
def client(ctx):
    return ctx.client


def owner_token(ctx) -> str:
    r = ctx.client.post("/api/identity/auth/login",
                        json={"email": ctx.owner_email,
                              "password": ctx.owner_pw, "tenant_id": ""})
    return r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signup_admin(client, email="ra@acme.io", company="Acme",
                 password="pw12345-2026") -> dict:
    """Round-9 onboarding contract: NEW workspaces default to MFA Required, so
    the founding admin's signup token is setup-scoped. This helper walks the
    full onboarding path — signup → TOTP enrol+verify (with the setup token) →
    password+TOTP login — and returns a FULL admin session.

    Returns {token, tenant, user, secret, email, password}.
    """
    from app import security

    r = client.post("/api/identity/auth/signup",
                    json={"email": email, "password": password,
                          "company_name": company})
    assert r.status_code == 201, r.text
    body = r.json()
    enrol = client.post("/api/identity/auth/mfa/enroll",
                        headers=auth(body["token"])).json()
    v = client.post("/api/identity/auth/mfa/verify",
                    json={"code": security.totp_code(enrol["secret"])},
                    headers=auth(body["token"]))
    assert v.status_code == 200, v.text
    login = client.post("/api/identity/auth/login",
                        json={"email": email, "password": password,
                              "tenant_id": body["tenant"]["id"],
                              "mfa_code": security.totp_code(enrol["secret"])})
    assert login.status_code == 200, login.text
    return {"token": login.json()["token"], "tenant": body["tenant"],
            "user": body["user"], "secret": enrol["secret"],
            "email": email, "password": password}
