"""Domain-event envelope + the canonical event-type catalog.

Every cross-service message on the bus is an :class:`EventEnvelope`. Services
publish and subscribe by ``type``; the envelope carries correlation fields
(tenant/dossier) and a free-form ``data`` payload. Event *names* live in
:class:`EventType` so producers and consumers can never drift on a string.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .ids import new_id, utcnow_iso


class EventType(str):
    """The platform event catalog (mirrors ADR-0001 + vision SAAS-REQ-011).

    Subclassing ``str`` keeps the values usable as plain strings while giving a
    single import site for the canonical names.
    """

    # validation context
    VALIDATION_COMPLETED = "validation.completed"
    VALIDATION_FAILED = "validation.failed"
    # transmission context
    TRANSMISSION_SENT = "transmission.sent"
    TRANSMISSION_HC_ACK = "transmission.hc_ack"
    # lifecycle context
    LIFECYCLE_TRANSITIONED = "lifecycle.transitioned"
    SERVICE_STANDARD_MISSED = "lifecycle.service_standard_missed"
    # dossier context
    SEQUENCE_PUBLISHED = "sequence.published"
    CONTENT_PLAN_ITEM_ASSIGNED = "dossier.content_plan.item_assigned"
    BILINGUAL_PM_BLOCKED = "dossier.bilingual_pm.blocked"
    # collaboration context
    COLLAB_TASK_ASSIGNED = "collab.task_assigned"
    COLLAB_COMMENT_ADDED = "collab.comment_added"
    # identity context
    TENANT_PROVISIONED = "identity.tenant_provisioned"
    USER_INVITED = "identity.user_invited"


class EventEnvelope(BaseModel):
    """A self-describing domain event carried on the bus."""

    id: str = Field(default_factory=new_id)
    type: str
    occurred_at: str = Field(default_factory=utcnow_iso)
    source: str = "unknown"
    tenant_id: str | None = None
    dossier_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make(cls, type: str, *, source: str = "unknown",
             tenant_id: str | None = None, dossier_id: str | None = None,
             data: dict | None = None) -> "EventEnvelope":
        """Convenience constructor stamping id/time automatically."""
        return cls(type=type, source=source, tenant_id=tenant_id,
                   dossier_id=dossier_id, data=dict(data or {}))
