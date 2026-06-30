"""Pydantic request models for the transmission API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConfigureIn(BaseModel):
    dossier_id: str = ""
    account_type: str = ""
    x509_certificate: str = ""
    registration_id: str = ""
    recipient_center: str = "HC"
    hc_direct_endpoint: str = ""


class TestRoundTripIn(BaseModel):
    dossier_id: str = ""
    mdn_received: bool = True
    fda_ack_received: bool = True
    hc_ack_received: bool = True


class SubmitIn(BaseModel):
    dossier_id: str = ""
    sequence: str = ""
    size_gb: float = 0.0
    production: bool = False


class AckIn(BaseModel):
    dossier_id: str = ""
    kind: str = ""          # mdn | fda | hc
    sequence: str = ""
    core_id: str = ""
    transport_rejected: bool = False
    notify: list[str] = Field(default_factory=list)
