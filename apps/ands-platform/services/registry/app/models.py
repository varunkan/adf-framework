"""Pydantic request models for the registry API."""

from __future__ import annotations

from pydantic import BaseModel


class RegistrationIn(BaseModel):
    product: str = ""
    country: str = "CA"
    dossier_id: str = ""
    din: str = ""
    drug_type: str = ""


class StatusIn(BaseModel):
    id: str
    status: str = ""


class ChecklistItemIn(BaseModel):
    year: int = 0            # 0 = current year (server decides)
    item_key: str = ""
    done: bool = True
