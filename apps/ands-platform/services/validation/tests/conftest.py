"""Shared fixtures — a fresh in-memory validation service per test."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteValidationRepository
from app.service import ValidationService


def clean_context():
    return {
        "dossier_id": "e123456",
        "files": [{"path": "m1/ca/cover.pdf", "kind": "pdf",
                   "pdf_version": "1.6"}],
        "leaves": [{"leaf_id": "l1", "href": "m1/ca/cover.pdf",
                    "checksum": "abc123"}],
    }


@pytest.fixture
def ctx():
    repo = SqliteValidationRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    service = ValidationService(repo, bus).register()
    client = TestClient(build_app(service))
    return SimpleNamespace(client=client, service=service, bus=bus, repo=repo)


@pytest.fixture
def client(ctx):
    return ctx.client
