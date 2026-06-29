"""Pydantic request models for the collaboration API.

Deliberately permissive on *business* rules (empty strings allowed) — the
authoritative validation lives in :mod:`app.domain`, which returns structured,
rule-tagged errors. These models only pin the wire shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CommentIn(BaseModel):
    target_type: str = ""
    target_id: str = ""
    author: str = ""
    body: str = ""
    parent_id: str | None = None


class TaskIn(BaseModel):
    title: str = ""
    assignee: str = ""
    due_date: str | None = None
    created_by: str = ""
    target_type: str = ""
    target_id: str = ""
    dossier_id: str = ""


class TaskStatusIn(BaseModel):
    id: str
    status: str = ""


class BlockingDefectIn(BaseModel):
    dossier_id: str = ""
    finding: dict = Field(default_factory=dict)
    recipients: list[str] = Field(default_factory=list)


class HcAckIn(BaseModel):
    dossier_id: str = ""
    core_id: str = ""
    recipients: list[str] = Field(default_factory=list)
