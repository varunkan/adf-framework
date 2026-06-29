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
