"""Shared fixtures — a fresh in-memory registry service per test."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteRegistrationRepository
from app.service import RegistryService


@pytest.fixture
def ctx():
    repo = SqliteRegistrationRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    # fake credential re-auth port: any email, password "signer-pass-1"
    service = RegistryService(
        repo, bus,
        reauth=lambda email, password, mfa: password == "signer-pass-1",
    ).register()
    client = TestClient(build_app(service))
    return SimpleNamespace(client=client, service=service, bus=bus, repo=repo)


@pytest.fixture
def client(ctx):
    return ctx.client
