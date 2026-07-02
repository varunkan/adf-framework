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


# -- HTTP ingest (services on per-process buses post events directly) -------

def test_http_ingest_lands_on_the_same_trail(ctx):
    ctx.bus.publish(EventEnvelope.make("x.first", source="s", dossier_id="e1"))
    rec = ctx.service.record_external({
        "source": "dossier", "event_type": "document.uploaded",
        "dossier_id": "e1", "tenant_id": "t1", "data": {"leaf": "l1"}})
    assert rec["category"] == "dossier"
    assert rec["action"] == "document.uploaded"
    events = ctx.service.list_audit(dossier_id="e1")["events"]
    assert [e["action"] for e in events] == ["x.first", "document.uploaded"]
    assert events[1]["detail"] == {"leaf": "l1"}
    assert events[1]["tenant_id"] == "t1"
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)  # ingest respects bus-event ordering


def test_http_ingest_requires_source_type_and_dossier(ctx):
    import pytest
    from ands_shared import ProblemError

    with pytest.raises(ProblemError):
        ctx.service.record_external({"source": "dossier"})


def test_list_audit_newest_first_with_limit(ctx):
    for i in range(5):
        ctx.bus.publish(EventEnvelope.make(f"evt.{i}", source="s",
                                           dossier_id="e9"))
    out = ctx.service.list_audit(dossier_id="e9", limit=2, newest_first=True)
    assert out["count"] == 2
    assert [e["action"] for e in out["events"]] == ["evt.4", "evt.3"]
