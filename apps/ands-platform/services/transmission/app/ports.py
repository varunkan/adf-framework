"""Repository port for the transmission service (ledger per dossier)."""

from __future__ import annotations

from typing import Protocol


class TransmissionRepository(Protocol):
    def save(self, ledger: dict, tenant_id: str = "") -> dict: ...
    # get() returns the ledger dict with a private "_tenant_id" ownership key
    # (the service strips it before the public response).
    def get(self, dossier_id: str) -> dict | None: ...
