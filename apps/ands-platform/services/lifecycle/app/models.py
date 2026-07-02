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
