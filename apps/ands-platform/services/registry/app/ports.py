"""Repository port for the registry service."""

from __future__ import annotations

from typing import Protocol


class RegistrationRepository(Protocol):
    def add(self, registration: dict) -> dict: ...
    def get(self, reg_id: str) -> dict | None: ...
    def list(self, *, product: str = "", country: str = "", din: str = "",
             status: str = "", dossier_id: str = "",
             tenant_id: str = "") -> list[dict]: ...
    def set_status(self, reg_id: str, status: str) -> dict | None: ...
