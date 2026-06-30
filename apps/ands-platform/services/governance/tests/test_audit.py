"""Event-sourced audit trail — governance records every bus event."""

from ands_shared import EventEnvelope, EventType


def test_every_published_event_is_recorded(ctx):
    ctx.bus.publish(EventEnvelope.make(EventType.VALIDATION_FAILED,
                                       source="validation", dossier_id="e1",
                                       data={"rule": "A09"}))
    ctx.bus.publish(EventEnvelope.make(EventType.TRANSMISSION_HC_ACK,
                                       source="transmission", dossier_id="e1",
                                       data={"core_id": "C1"}))
    audit = ctx.service.list_audit()
    assert audit["count"] == 2
    actions = [e["action"] for e in audit["events"]]
    assert "validation.failed" in actions and "transmission.hc_ack" in actions


def test_audit_filter_by_dossier(ctx):
    ctx.bus.publish(EventEnvelope.make("x.y", source="s", dossier_id="e1"))
    ctx.bus.publish(EventEnvelope.make("x.z", source="s", dossier_id="e2"))
    assert ctx.service.list_audit(dossier_id="e1")["count"] == 1


def test_audit_trail_is_append_only_ordered(ctx):
    for i in range(3):
        ctx.bus.publish(EventEnvelope.make(f"evt.{i}", source="s"))
    seqs = [e["seq"] for e in ctx.service.list_audit()["events"]]
    assert seqs == sorted(seqs)  # monotonic order preserved
