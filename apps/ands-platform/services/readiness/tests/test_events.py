"""Event-driven projection — the BFF consumes every service's events."""

from ands_shared import EventEnvelope, EventType


def test_validation_event_projects_into_dashboard(ctx):
    ctx.bus.publish(EventEnvelope.make(
        EventType.VALIDATION_FAILED, source="validation", dossier_id="e1",
        data={"blocking": True, "error_count": 2, "warning_count": 1}))
    card = ctx.service.get("e1")
    assert card["status"] == "BLOCKED"
    val = next(t for t in card["tiles"] if t["key"] == "validation")
    assert val["errors"] == 2


def test_full_event_flow_to_ready(ctx):
    ctx.bus.publish(EventEnvelope.make(
        EventType.VALIDATION_COMPLETED, source="validation", dossier_id="e1",
        data={"blocking": False, "error_count": 0, "warning_count": 0}))
    ctx.bus.publish(EventEnvelope.make(
        EventType.LIFECYCLE_TRANSITIONED, source="lifecycle", dossier_id="e1",
        data={"phase": "Review", "status": "Active"}))
    ctx.bus.publish(EventEnvelope.make(
        EventType.TRANSMISSION_HC_ACK, source="transmission", dossier_id="e1",
        data={"core_id": "C1"}))
    card = ctx.service.get("e1")
    assert card["status"] == "READY"
    lc = next(t for t in card["tiles"] if t["key"] == "lifecycle")
    assert "Review" in lc["value"]
    tx = next(t for t in card["tiles"] if t["key"] == "transmission")
    assert tx["delivered"] is True


def test_bilingual_pm_block_event(ctx):
    ctx.bus.publish(EventEnvelope.make(
        EventType.VALIDATION_COMPLETED, source="validation", dossier_id="e1",
        data={"blocking": False, "error_count": 0}))
    ctx.bus.publish(EventEnvelope.make(
        EventType.BILINGUAL_PM_BLOCKED, source="dossier", dossier_id="e1",
        data={"findings": [{"rule": "pm_fr_missing"}]}))
    assert ctx.service.get("e1")["status"] == "BLOCKED"


def test_dashboard_counts_multiple_dossiers(ctx):
    ctx.bus.publish(EventEnvelope.make(
        EventType.VALIDATION_COMPLETED, source="validation", dossier_id="e1",
        data={"error_count": 0}))
    ctx.bus.publish(EventEnvelope.make(
        EventType.VALIDATION_FAILED, source="validation", dossier_id="e2",
        data={"error_count": 5}))
    dash = ctx.service.dashboard()
    assert dash["total"] == 2 and dash["ready"] == 1 and dash["blocked"] == 1
