"""Pydantic request models for the fees API."""

from __future__ import annotations

from pydantic import BaseModel


class MitigationIn(BaseModel):
    fee: float = 0.0
    small_business: bool = False
    first_submission: bool = False
    attestation_uploaded: bool = False
    defer_until_noc: bool = False
