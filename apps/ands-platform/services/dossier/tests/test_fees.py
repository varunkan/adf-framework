"""HC ANDS fee engine — pure (Fees Order, CPI-indexed each Apr 1)."""

import pytest

from app import fees


# --- fiscal-year selection across the April-1 boundary ----------------------

def test_fiscal_year_boundary_april_1():
    assert fees.fiscal_year("2025-03-31") == "2024-25"
    assert fees.fiscal_year("2025-04-01") == "2025-26"
    assert fees.fiscal_year("2026-03-31") == "2025-26"
    assert fees.fiscal_year("2026-04-01") == "2026-27"


def test_ands_review_fee_selects_fy_by_as_of():
    before = fees.ands_review_fee("2026-03-31")
    after = fees.ands_review_fee("2026-04-01")
    assert before["fiscal_year"] == "2025-26"
    assert before["amount"] == 70750.0
    assert after["fiscal_year"] == "2026-27"
    assert after["amount"] == 71953.0
    # never hard-coded to one number: the two figures differ
    assert before["amount"] != after["amount"]


def test_ands_review_fee_shape():
    fee = fees.ands_review_fee("2025-06-15")
    assert fee["currency"] == "CAD"
    assert "comparative-studies" in fee["basis"].lower()
    assert set(fee) >= {"fiscal_year", "amount", "currency", "basis"}


def _load_mesh_fees():
    """Load the sibling mesh ``fees`` service module by file path (its own
    ``app`` package collides with the dossier's, so import it standalone)."""
    import importlib.util
    import pathlib
    mesh_file = (pathlib.Path(fees.__file__).resolve()
                 .parents[2] / "fees" / "app" / "fees.py")
    spec = importlib.util.spec_from_file_location("_mesh_fees", mesh_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ands_review_fee_matches_mesh_figures():
    """Sample date figures must match the mesh fees service verbatim."""
    mesh = _load_mesh_fees()
    # ANDS review fee == mesh comparative-studies grouping for the same FY
    resolved = mesh.resolve_ands_fee("2026-05-01")
    ours = fees.ands_review_fee("2026-05-01")
    assert ours["amount"] == resolved["amount"] == 71953.0
    assert ours["fiscal_year"] == resolved["fiscal_year"]
    # Right-to-sell (prescription DIN) must also match the mesh table verbatim.
    mesh_rts = mesh.resolve_right_to_sell("prescription", "2026-05-01")
    assert fees.right_to_sell("2026-05-01")["amount"] == mesh_rts["amount"]
    assert fees.right_to_sell_due_date("2026-05-01") == mesh_rts["due_date"]


def test_carry_forward_before_first_published_year():
    # a date earlier than any published FY falls back to the earliest figure
    early = fees.ands_review_fee("2020-01-01")
    assert early["amount"] == 70750.0
    assert early["amount_fiscal_year"] == "2025-26"


# --- SME mitigation ---------------------------------------------------------

def test_sme_50_percent_reduction():
    fee = fees.ands_review_fee("2025-06-01")["amount"]  # 70750.0
    m = fees.small_business_mitigation(fee, sme_granted=True,
                                       first_ever_submission=False)
    assert m["reduction"] == 35375.0
    assert m["payable"] == 35375.0
    assert m["waived"] is False
    assert "granted" in m["note"].lower()


def test_sme_first_ever_waiver_payable_zero():
    fee = fees.ands_review_fee("2026-06-01")["amount"]  # 71953.0
    m = fees.small_business_mitigation(fee, sme_granted=True,
                                       first_ever_submission=True)
    assert m["waived"] is True
    assert m["payable"] == 0.0
    assert m["reduction"] == 71953.0


def test_no_sme_status_full_fee_payable():
    m = fees.small_business_mitigation(70750.0, sme_granted=False,
                                       first_ever_submission=True)
    assert m["payable"] == 70750.0
    assert m["reduction"] == 0.0
    assert m["waived"] is False
    # must note that status has to be granted before filing
    assert "before" in m["note"].lower()


def test_mitigation_note_mentions_pre_grant_requirement():
    m = fees.small_business_mitigation(70750.0, sme_granted=True,
                                       first_ever_submission=False)
    assert "before" in m["note"].lower() and "grant" in m["note"].lower()


# --- Right-to-sell ----------------------------------------------------------

def test_right_to_sell_due_oct_1():
    rts = fees.right_to_sell("2025-06-15")
    assert rts["due_date"] == "2025-10-01"
    assert rts["amount"] == 5531.0
    assert rts["currency"] == "CAD"


def test_right_to_sell_due_date_uses_fiscal_year_start():
    # Feb 2026 is still FY 2025-26 -> Oct 1, 2025
    assert fees.right_to_sell("2026-02-01")["due_date"] == "2025-10-01"
    # Apr 2026 is FY 2026-27 -> Oct 1, 2026
    assert fees.right_to_sell("2026-04-15")["due_date"] == "2026-10-01"


def test_right_to_sell_fy_selection_and_sme_reduction():
    full = fees.right_to_sell("2026-05-01")
    assert full["amount"] == 5626.0
    sme = fees.right_to_sell("2026-05-01", sme_granted=True)
    assert sme["amount"] == 2813.0  # 50% of 5626.0
    assert "50%" in sme["note"]


def test_bad_as_of_raises():
    with pytest.raises(ValueError):
        fees.ands_review_fee("")
