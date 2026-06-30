"""Pydantic request models for the journey BFF. Intake/dossier bodies allow
extra fields because the 'tell me about your drug' answers are free-form nested
(crp / generic / be_study / …)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StartIn(BaseModel):
    title: str = ""
    tenant_id: str = ""
    answers: dict | None = None      # optional initial 'about your drug' intake


class IntakeIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    session_id: str = ""             # when set, the assessment is stored on it


class AdvanceIn(BaseModel):
    step: str
    data: dict = Field(default_factory=dict)


class DossierAssessIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    dossier_id: str = ""
    branch: str = "pharmaceutical"
    request_date: str = ""
    first_filing_date: str = ""
