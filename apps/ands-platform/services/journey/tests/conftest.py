"""Shared fixtures — a fresh in-memory journey BFF per test."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteSessionRepository
from app.service import JourneyService


@pytest.fixture
def ctx():
    repo = SqliteSessionRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    service = JourneyService(repo, bus)
    client = TestClient(build_app(service))
    return SimpleNamespace(client=client, service=service, bus=bus, repo=repo)


@pytest.fixture
def client(ctx):
    return ctx.client
