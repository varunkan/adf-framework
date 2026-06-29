"""Event-driven triggers — collaboration reacts to other services' events.

These prove the decoupled, event-bus design: a ``validation.failed`` or
``transmission.hc_ack`` published by another service (here, onto the in-memory
bus) makes collaboration create the right notifications, with no direct call.
"""

from ands_shared import EventEnvelope, EventType

from app import domain


def test_validation_failed_event_creates_blocking_notification(ctx):
    ctx.bus.publish(EventEnvelope.make(
        EventType.VALIDATION_FAILED, source="validation",
        dossier_id="e123456",
        data={"finding": {"rule": "A09", "message": "PDF is encrypted"},
              "recipients": ["alice", "bob"]}))
    inbox = ctx.service.inbox("alice")
    assert inbox["unread"] == 1
    assert inbox["notifications"][0]["kind"] == domain.KIND_BLOCKING_DEFECT
    assert "A09" in inbox["notifications"][0]["body"]


def test_hc_ack_event_enqueues_email(ctx):
    ctx.bus.publish(EventEnvelope.make(
        EventType.TRANSMISSION_HC_ACK, source="transmission",
        dossier_id="e123456",
        data={"core_id": "CORE-1", "recipients": ["ra"]}))
    outbox = ctx.service.outbox()
    assert outbox["pending"] >= 1
    assert any("CORE-1" in e["body"] for e in outbox["emails"])


def test_creating_task_publishes_assignment_event(ctx):
    ctx.service.create_task({"title": "review CMC", "assignee": "bob",
                             "dossier_id": "e123456"})
    emitted = ctx.bus.events_of(EventType.COLLAB_TASK_ASSIGNED)
    assert len(emitted) == 1
    assert emitted[0].data["assignee"] == "bob"
