"""Pure fee domain (REQ-035/036/037)."""

import pytest

from app import fees


def test_fiscal_year_boundaries():
    assert fees.fiscal_year("2025-04-01") == "2025-26"
    assert fees.fiscal_year("2025-03-31") == "2024-25"


def test_ands_fee_is_comparative_studies_current_amount():
    r = fees.resolve_ands_fee("2025-06-01")
    assert r["grouping"] == "comparative-studies"
    assert r["amount"] == 70750.0
    assert r["amount"] != fees.COMPARATIVE_STUDIES_ANCHOR_SEED


def test_ands_fee_next_fiscal_year():
    assert fees.resolve_ands_fee("2026-06-01")["amount"] == 71953.0


def test_escalation_bases():
    assert fees.escalate(100.0, fees.BASIS_MINISTERIAL_2PCT) == 102.0
    assert fees.escalate(100.0, fees.BASIS_CPI, 0.03) == 103.0
    with pytest.raises(ValueError):
        fees.escalate(100.0, "weird")


def test_first_submission_full_remission():
    r = fees.evaluate_fee_mitigation({"fee": 70750.0, "small_business": True,
                                      "first_submission": True})
    assert r["remission_rate"] == 1.0
    assert r["net_fee"] == 0.0
    assert r["invoice_status"] == "remitted"


def test_subsequent_remission_needs_attestation():
    blocked = fees.evaluate_fee_mitigation({"fee": 100.0, "small_business": True})
    assert blocked["requires_attestation"] is True
    assert blocked["net_fee"] == 100.0
    ok = fees.evaluate_fee_mitigation({"fee": 100.0, "small_business": True,
                                       "attestation_uploaded": True})
    assert ok["remission_rate"] == 0.5 and ok["net_fee"] == 50.0


def test_deferral_status():
    r = fees.evaluate_fee_mitigation({"fee": 100.0, "defer_until_noc": True})
    assert r["invoice_status"] == "deferred-until-noc" and r["deferred"]


def test_right_to_sell_due_date_and_reminder():
    rec = fees.right_to_sell_status("prescription", "2025-09-15", paid=False)
    assert rec["amount"] == 5531.0
    assert rec["due_date"] == "2025-10-01"
    assert rec["reminder_due"] is True   # within 60 days, unpaid
    assert rec["overdue"] is False


def test_right_to_sell_unknown_type_raises():
    with pytest.raises(ValueError):
        fees.resolve_right_to_sell("moon-cheese", "2025-09-15")
