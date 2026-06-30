"""Shared fixtures — a fresh in-memory lifecycle service per test."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteLifecycleRepository
from app.service import LifecycleService


@pytest.fixture
def ctx():
    repo = SqliteLifecycleRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    service = LifecycleService(repo, bus).register()
    client = TestClient(build_app(service))
    return SimpleNamespace(client=client, service=service, bus=bus, repo=repo)


@pytest.fixture
def client(ctx):
    return ctx.client
