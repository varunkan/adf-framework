"""Repository port for the governance audit trail (append-only)."""

from __future__ import annotations

from typing import Protocol


class AuditRepository(Protocol):
    def append(self, event: dict) -> dict: ...
    def list(self, *, category: str = "", dossier_id: str = "") -> list[dict]: ...
    def count(self) -> int: ...
