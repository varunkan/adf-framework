"""Pydantic request models for the webhooks API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubscriptionIn(BaseModel):
    url: str = ""
    event_types: list[str] = Field(default_factory=lambda: ["*"])
    tenant_id: str = ""
    secret: str = ""
