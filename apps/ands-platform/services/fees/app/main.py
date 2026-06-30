"""Composition root — the fees service is stateless (no DB, no bus)."""

from __future__ import annotations

from .api import build_app
from .service import FeesService

app = build_app(FeesService())
