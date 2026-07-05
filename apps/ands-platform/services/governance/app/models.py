"""Pydantic request models for the governance API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QaReviewIn(BaseModel):
    reviewer: str = ""
    role: str = ""
    audit_trail_reviewed: bool = False
    at: str = ""
    comment: str = ""


class SignIn(BaseModel):
    signer: str = ""
    role: str = ""
    auth_method: str = ""
    meaning: str = ""
    # None => caller omitted it, so the domain defaults the signing reason from
    # the meaning. An explicit "" (from the web capture) is a rejected signature.
    reason: str | None = None
    at: str = ""
    tz: str = ""
    artifacts: list[dict] = Field(default_factory=list)


class VerifyIn(BaseModel):
    manifest: dict = Field(default_factory=dict)
    current: Any = None


class GateIn(BaseModel):
    review: dict = Field(default_factory=dict)
    manifest: dict = Field(default_factory=dict)
    current: Any = None


class HcRequestIn(BaseModel):
    approach: str = ""
    org: str = ""
    sponsor: str = ""


class HcRecordIn(BaseModel):
    approach: str = ""
    accepted: bool = False
    org: str = ""
    reference: str = ""
    at: str = ""


class AuditRecordIn(BaseModel):
    """HTTP ingest payload — services without a shared bus post events here."""

    source: str = ""
    event_type: str = ""
    dossier_id: str = ""
    tenant_id: str = ""
    actor: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class ExportIn(BaseModel):
    tenant_id: str = ""
    attachments: dict = Field(default_factory=dict)


class LegalHoldIn(BaseModel):
    tenant_id: str = ""
    active: bool = False


class DeletionIn(BaseModel):
    tenant_id: str = ""
