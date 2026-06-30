"""Repository port for the readiness projection store."""

from __future__ import annotations

from typing import Protocol


class ProjectionRepository(Protocol):
    def get(self, dossier_id: str) -> dict | None: ...
    def upsert(self, dossier_id: str, signals: dict) -> dict: ...
    def all(self) -> dict: ...
