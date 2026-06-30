"""Shared fixtures — a fresh in-memory readiness BFF per test."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteProjectionRepository
from app.service import ReadinessService


@pytest.fixture
def ctx():
    repo = SqliteProjectionRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    service = ReadinessService(repo, bus).register()
    client = TestClient(build_app(service))
    return SimpleNamespace(client=client, service=service, bus=bus, repo=repo)


@pytest.fixture
def client(ctx):
    return ctx.client
