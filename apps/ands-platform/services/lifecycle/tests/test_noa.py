"""Form V + Notice of Allegation register — PM(NOC) Regulations (generics)."""

from datetime import date

import pytest

from app import noa


def _record(allegation="not_infringed", **over):
    data = {"dossier_id": "e1", "patent_number": "CA2500000",
            "allegation": allegation, "form_v_date": "2025-02-01"}
    data.update(over)
    return noa.validate_allegation(data)["record"]


# -- validation ------------------------------------------------------------
def test_validate_requires_fields():
    bad = noa.validate_allegation({"allegation": "pizza"})
    rules = {e["rule"] for e in bad["errors"]}
    assert {"dossier_id_required", "patent_number_required",
            "allegation_invalid", "form_v_date_required"} <= rules


def test_validate_rejects_malformed_form_v_date():
    bad = noa.validate_allegation({
        "dossier_id": "e1", "patent_number": "CA1", "allegation": "invalid",
        "form_v_date": "not-a-date"})
    assert {"rule": "form_v_date_invalid"} in [
        {"rule": e["rule"]} for e in bad["errors"]]


def test_validate_ok_noa_required_starts_draft():
    ok = noa.validate_allegation({
        "dossier_id": "e1", "patent_number": "CA2500000",
        "allegation": "not_infringed", "form_v_date": "2025-02-01"})
    assert ok["valid"]
    rec = ok["record"]
    assert rec["noa_required"] is True
    assert rec["status"] == noa.STATUS_DRAFT
    assert rec["allegation_label"]


def test_validate_accept_expiry_needs_no_noa_and_is_clear():
    rec = _record("accept_expiry")
    assert rec["noa_required"] is False
    assert rec["status"] == noa.STATUS_CLEAR


# -- serve → 45-day action window -------------------------------------------
def test_serve_starts_45_day_action_window():
    rec = noa.serve(_record(), "2025-03-01")
    assert rec["status"] == noa.STATUS_SERVED
    assert rec["served_date"] == "2025-03-01"
    assert rec["action_window_end"] == "2025-04-15"


def test_serve_rejected_when_no_noa_required():
    with pytest.raises(noa.NoaError) as exc:
        noa.serve(_record("no_claim"), "2025-03-01")
    assert exc.value.rule == "noa_not_required"


def test_serve_twice_rejected():
    rec = noa.serve(_record(), "2025-03-01")
    with pytest.raises(noa.NoaError) as exc:
        noa.serve(rec, "2025-03-02")
    assert exc.value.rule == "not_draft"


# -- s.6 action → 24-month statutory stay ------------------------------------
def test_action_starts_24_month_stay():
    rec = noa.serve(_record(), "2025-03-01")
    rec = noa.commence_action(rec, "2025-04-01")
    assert rec["status"] == noa.STATUS_ACTION
    assert rec["stay_start"] == "2025-04-01"
    assert rec["stay_end"] == "2027-04-01"


def test_action_outside_45_day_window_rejected():
    rec = noa.serve(_record(), "2025-03-01")
    with pytest.raises(noa.NoaError) as exc:
        noa.commence_action(rec, "2025-05-01")
    assert exc.value.rule == "action_window_expired"


def test_action_before_serve_rejected():
    with pytest.raises(noa.NoaError) as exc:
        noa.commence_action(_record(), "2025-04-01")
    assert exc.value.rule == "not_served"


def test_add_months_clamps_month_end():
    assert noa.add_months("2025-01-31", 1) == date(2025, 2, 28)
    assert noa.add_months("2024-02-29", 24) == date(2026, 2, 28)


# -- computed clocks (as_of) --------------------------------------------------
def test_clocks_served_days_remaining():
    rec = noa.serve(_record(), "2025-03-01")
    view = noa.with_clocks(rec, "2025-03-10")
    assert view["status"] == noa.STATUS_SERVED
    assert view["action_days_remaining"] == 36
    assert view["as_of"] == "2025-03-10"


def test_clocks_clear_once_45_days_pass_without_action():
    rec = noa.serve(_record(), "2025-03-01")
    view = noa.with_clocks(rec, "2025-04-16")
    assert view["status"] == noa.STATUS_CLEAR
    assert view["action_days_remaining"] == 0


def test_clocks_stay_running_then_resolved():
    rec = noa.commence_action(noa.serve(_record(), "2025-03-01"), "2025-04-01")
    running = noa.with_clocks(rec, "2026-04-01")
    assert running["status"] == noa.STATUS_STAY_RUNNING
    assert running["stay_days_remaining"] == 365
    over = noa.with_clocks(rec, "2027-04-01")
    assert over["status"] == noa.STATUS_RESOLVED
    assert over["stay_days_remaining"] == 0


def test_resolve_ends_the_stay_early():
    rec = noa.commence_action(noa.serve(_record(), "2025-03-01"), "2025-04-01")
    rec = noa.resolve(rec, "2026-01-15", outcome="action dismissed")
    assert rec["status"] == noa.STATUS_RESOLVED
    assert rec["resolved_at"] == "2026-01-15"
    view = noa.with_clocks(rec, "2026-06-01")
    assert view["status"] == noa.STATUS_RESOLVED


def test_resolve_requires_a_commenced_action():
    with pytest.raises(noa.NoaError) as exc:
        noa.resolve(_record(), "2026-01-15")
    assert exc.value.rule == "no_action"


# -- API ----------------------------------------------------------------------
def _create(client, **over):
    body = {"dossier_id": "e1", "patent_number": "CA2500000",
            "allegation": "not_infringed", "form_v_date": "2025-02-01"}
    body.update(over)
    return client.post("/api/lifecycle/noa", json=body)


def test_create_and_list_via_api(client):
    r = _create(client)
    assert r.status_code == 201 and r.json()["id"]
    _create(client, patent_number="CA2600000", allegation="accept_expiry")
    got = client.get("/api/lifecycle/noa", params={"dossier_id": "e1"}).json()
    assert got["count"] == 2
    assert {a["patent_number"] for a in got["allegations"]} == \
        {"CA2500000", "CA2600000"}


def test_create_invalid_allegation_422(client):
    r = _create(client, allegation="pizza")
    assert r.status_code == 422


def test_serve_and_action_flow_via_api(client):
    nid = _create(client).json()["id"]
    served = client.post(f"/api/lifecycle/noa/{nid}/serve",
                         json={"served_date": "2025-03-01"})
    assert served.status_code == 200
    assert served.json()["action_window_end"] == "2025-04-15"
    acted = client.post(f"/api/lifecycle/noa/{nid}/action",
                        json={"action_date": "2025-04-01",
                              "court_file": "T-1000-25"})
    assert acted.status_code == 200
    assert acted.json()["stay_end"] == "2027-04-01"
    got = client.get("/api/lifecycle/noa",
                     params={"dossier_id": "e1", "as_of": "2026-04-01"}).json()
    row = got["allegations"][0]
    assert row["status"] == "stay_running"
    assert row["stay_days_remaining"] == 365
    assert row["court_file"] == "T-1000-25"


def test_serve_unknown_noa_404(client):
    r = client.post("/api/lifecycle/noa/ghost/serve",
                    json={"served_date": "2025-03-01"})
    assert r.status_code == 404


def test_illegal_serve_409(client):
    nid = _create(client, allegation="accept_expiry").json()["id"]
    r = client.post(f"/api/lifecycle/noa/{nid}/serve",
                    json={"served_date": "2025-03-01"})
    assert r.status_code == 409
