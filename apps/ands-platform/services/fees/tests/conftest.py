"""Shared fixtures — the stateless fees service."""

import pytest
from fastapi.testclient import TestClient

from app.api import build_app
from app.service import FeesService


@pytest.fixture
def client():
    return TestClient(build_app(FeesService()))
