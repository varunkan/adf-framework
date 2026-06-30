"""Dossier-ID guidance — format, per-branch digits, 8-week warn-only lead time."""

from app import dossier_id


def test_format_valid_and_invalid():
    assert dossier_id.is_valid_dossier_id("e123456")
    assert dossier_id.is_valid_dossier_id("e1234567")     # 7 digits ok
    assert not dossier_id.is_valid_dossier_id("e12345")    # too short
    assert not dossier_id.is_valid_dossier_id("E123456")   # uppercase
    assert not dossier_id.is_valid_dossier_id("123456")    # no prefix


def test_master_file_branch_digit_constraints():
    # Master File eCTD must be e+6 (not e+7); non-eCTD must be f+7
    assert dossier_id.dossier_id_conforms("e123456", "master-file-ectd")
    assert not dossier_id.dossier_id_conforms("e1234567", "master-file-ectd")
    assert dossier_id.dossier_id_conforms("f1234567", "master-file-non-ectd")
    assert not dossier_id.dossier_id_conforms("f123456", "master-file-non-ectd")


def test_lead_time_warns_only_when_more_than_8_weeks_ahead():
    early = dossier_id.assess_lead_time("2026-01-01", "2026-06-01")  # ~21 weeks
    assert early["too_early"] is True and early["warning"]
    ok = dossier_id.assess_lead_time("2026-05-01", "2026-06-01")     # ~4 weeks
    assert ok["too_early"] is False and ok["warning"] is None


def test_lead_time_never_gates_on_unparseable_dates():
    r = dossier_id.assess_lead_time("", "")
    assert r["assessable"] is False and r["too_early"] is False


def test_assess_combines_format_and_lead_time():
    r = dossier_id.assess({"dossier_id": "e123456", "branch": "pharmaceutical",
                           "request_date": "2026-05-01",
                           "first_filing_date": "2026-06-01"})
    assert r["valid_branch"] and r["format_ok"] is True
    assert r["lead_time"]["too_early"] is False


def test_assess_reports_format_error():
    r = dossier_id.assess({"dossier_id": "bad", "branch": "pharmaceutical"})
    assert r["format_ok"] is False and "not a valid" in r["format_error"]
