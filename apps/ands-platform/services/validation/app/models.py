"""Pydantic request models for the validation API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidateIn(BaseModel):
    context: dict = Field(default_factory=dict)
    version: str | None = None
    dossier_id: str = ""
    sequence: str = ""
    notify: list[str] = Field(default_factory=list)


class InlineIn(BaseModel):
    context: dict = Field(default_factory=dict)
    version: str | None = None


class FixIn(BaseModel):
    context: dict = Field(default_factory=dict)
    fix_id: str = ""
    file: str = ""
