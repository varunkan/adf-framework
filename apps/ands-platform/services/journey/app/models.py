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


class PlaceDocIn(BaseModel):
    slot_key: str
    doc: str | dict = ""                       # a filename or a doc descriptor
    languages: list | None = None              # for the bilingual PM slot


class NoticeIn(BaseModel):
    type: str                                  # SDN / SAL / clarifax / NOD / NON / NOC
    date: str = ""                             # YYYY-MM-DD


class PauseIn(BaseModel):
    type: str                                  # the notice type to pause/resume
    paused: bool = True
