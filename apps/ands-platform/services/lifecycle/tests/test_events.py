"""Event emissions — lifecycle.transitioned + service_standard_missed."""

from datetime import timedelta

from ands_shared import EventType

from app import hc_calendar


def test_start_and_transition_emit_transitioned(ctx):
    ctx.service.start_lifecycle({"dossier_id": "e1", "submission_type": "ANDS",
                                 "received_date": "2025-01-06"})
    ctx.service.transition({"dossier_id": "e1", "kind": "screening",
                            "value": "SAL", "date": "2025-01-10"})
    events = ctx.bus.events_of(EventType.LIFECYCLE_TRANSITIONED)
    assert len(events) == 2
    assert events[-1].data["phase"] == "Review"


def test_late_noc_emits_service_standard_missed(ctx):
    ctx.service.start_lifecycle({"dossier_id": "e1", "submission_type": "ANDS",
                                 "received_date": "2025-01-06",
                                 "fee_paid": 70750.0})
    sal = ctx.service.transition({"dossier_id": "e1", "kind": "screening",
                                  "value": "SAL", "date": "2025-01-10"})
    late = (hc_calendar._as_date(sal["review_due"])
            + timedelta(days=10)).isoformat()
    ctx.service.transition({"dossier_id": "e1", "kind": "decision",
                            "value": "NOC", "date": late})
    missed = ctx.bus.events_of(EventType.SERVICE_STANDARD_MISSED)
    assert len(missed) == 1
    assert missed[0].data["credit_amount"] == 17687.5
