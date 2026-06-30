"""Pure DSTS lifecycle state machine."""

from datetime import timedelta

import pytest

from app import hc_calendar, lifecycle


def _plus(iso: str, days: int) -> str:
    return (hc_calendar._as_date(iso) + timedelta(days=days)).isoformat()


def test_start_begins_in_screening():
    s = lifecycle.start("e123456", "ANDS", "2025-01-06")
    assert s["phase"] == "Screening" and s["status"] == "Active"
    assert s["screening_due"] and s["review_due"] is None


def test_sal_moves_to_review_with_review_due():
    s = lifecycle.start("e1", "ANDS", "2025-01-06")
    s = lifecycle.apply_screening(s, "SAL", "2025-01-10")
    assert s["phase"] == "Review" and s["review_due"]


def test_sdn_makes_inactive_90_for_ands():
    s = lifecycle.start("e1", "ANDS", "2025-01-06")
    s = lifecycle.apply_screening(s, "SDN", "2025-01-10")
    assert s["status"] == "Inactive-90"
    assert any(t["kind"] == "SDN" for t in s["timers"])


def test_srl_rejects():
    s = lifecycle.start("e1", "ANDS", "2025-01-06")
    s = lifecycle.apply_screening(s, "SRL", "2025-01-10")
    assert s["phase"] == "Complete" and s["status"] == "Screening-Rejected"


def test_noc_on_time_has_no_fee_credit():
    s = lifecycle.start("e1", "ANDS", "2025-01-06")
    s = lifecycle.apply_screening(s, "SAL", "2025-01-10")
    on_time = _plus(s["review_due"], -1)
    s = lifecycle.apply_decision(s, "NOC", on_time)
    assert s["status"] == "Approved" and s["fee_credit"] is None


def test_noc_late_triggers_25pct_fee_credit():
    s = lifecycle.start("e1", "ANDS", "2025-01-06", fee_paid=70750.0)
    s = lifecycle.apply_screening(s, "SAL", "2025-01-10")
    late = _plus(s["review_due"], 10)
    s = lifecycle.apply_decision(s, "NOC", late)
    assert s["fee_credit"]["missed_service_standard"] is True
    assert s["fee_credit"]["credit_amount"] == 17687.5


def test_decision_before_review_raises():
    s = lifecycle.start("e1", "ANDS", "2025-01-06")
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.apply_decision(s, "NOC", "2025-02-01")


def test_din_uses_inactive_45():
    s = lifecycle.start("e1", "DIN", "2025-01-06")
    s = lifecycle.apply_screening(s, "SAL", "2025-01-10")
    s = lifecycle.apply_decision(s, "NOD", "2025-02-01")
    assert s["status"] == "Inactive-45"


def test_cannot_withdraw_approved():
    s = lifecycle.start("e1", "ANDS", "2025-01-06")
    s = lifecycle.apply_screening(s, "SAL", "2025-01-10")
    s = lifecycle.apply_decision(s, "NOC", _plus(s["review_due"], -1))
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.withdraw(s, "change of plans")
