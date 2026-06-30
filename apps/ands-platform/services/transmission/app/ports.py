"""Repository port for the transmission service (ledger per dossier)."""

from __future__ import annotations

from typing import Protocol


class TransmissionRepository(Protocol):
    def save(self, ledger: dict) -> dict: ...
    def get(self, dossier_id: str) -> dict | None: ...
