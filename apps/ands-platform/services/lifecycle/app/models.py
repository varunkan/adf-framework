"""Pydantic request models for the lifecycle API."""

from __future__ import annotations

from pydantic import BaseModel


class StartIn(BaseModel):
    dossier_id: str = ""
    submission_type: str = "ANDS"
    received_date: str = ""
    fee_paid: float | None = None


class TransitionIn(BaseModel):
    dossier_id: str = ""
    kind: str = ""          # screening | decision | withdraw
    value: str = ""         # SAL/SDN/SRL | NOC/NOD/NON
    date: str = ""
    reason: str = ""


class DeadlineIn(BaseModel):
    start: str = ""
    days: int = 0
    notice_type: str = ""
    basis: str | None = None


class CorrespondenceIn(BaseModel):
    dossier_id: str = ""
    kind: str = ""
    subject: str = ""
    body: str = ""
    direction: str = "inbound"
    received_at: str = ""
    reference: str = ""


class AttachmentIn(BaseModel):
    filename: str = ""
    content_type: str = ""
    data_base64: str = ""


class VerifiedDateIn(BaseModel):
    # Round-9 (operations, n=4): a manual verified-date override for one
    # calculated clock — records the externally-verified value + its source.
    dossier_id: str = ""
    clock_key: str = ""       # e.g. noa:{id}:action_window · rts:{reg}:{fy}
    verified_date: str = ""   # the value the user verified externally
    calculated_date: str = "" # what the tool showed at verification time
    source_ref: str = ""      # where it was verified (HC letter, Vault RIM…)


class NoticeIn(BaseModel):
    dossier_id: str = ""
    notice: str = ""          # SAL/SDN/SRL/NOC/NOD/NON
    date: str = ""
    subject: str = ""
    reference: str = ""


class NoaIn(BaseModel):
    dossier_id: str = ""
    patent_number: str = ""
    allegation: str = ""      # not_infringed|invalid|accept_expiry|no_claim
    form_v_date: str = ""


class NoaServeIn(BaseModel):
    served_date: str = ""


class NoaActionIn(BaseModel):
    action_date: str = ""
    court_file: str = ""


class ShortageIn(BaseModel):
    dossier_id: str = ""
    din: str = ""
    kind: str = ""            # shortage | discontinuation
    tier: int | None = None   # 1 | 2 | 3
    reason: str = ""
    anticipated_start: str = ""
    anticipated_end: str = ""
    became_aware: str = ""
    reported_at: str = ""


class DelLinkIn(BaseModel):
    dossier_id: str = ""
    del_number: str = ""
    sites: list[str] = []
