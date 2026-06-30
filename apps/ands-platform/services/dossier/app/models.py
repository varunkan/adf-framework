"""Pydantic request models for the dossier API (business rules live in domain)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContentPlanIn(BaseModel):
    dossier_id: str = ""
    submission_type: str = ""
    cs_be_only: bool = False


class ItemAssignIn(BaseModel):
    id: str
    assignee: str = ""
    due_date: str | None = None


class ItemStatusIn(BaseModel):
    id: str
    status: str = ""


class PmLeafIn(BaseModel):
    dossier_id: str = ""
    lang: str = ""
    title: str = ""
    version: int = 1
    leaf_id: str | None = None


class AdminSequenceIn(BaseModel):
    dossier_id: str = ""
    activity: str = ""
    sequence: str = ""
    operations: list[dict] = Field(default_factory=list)
    present_documents: list[dict] = Field(default_factory=list)
    cover_letter_generated: bool = True
