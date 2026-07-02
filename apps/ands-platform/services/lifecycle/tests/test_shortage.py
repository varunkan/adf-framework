"""Drug shortage / discontinuation reports + DEL linkage (C.01.014.8+)."""

from app import shortage


def _report(**over):
    base = {"dossier_id": "e1", "din": "02531234", "kind": "shortage",
            "tier": 3, "reason": "API supply interruption",
            "anticipated_start": "2026-02-01",
            "became_aware": "2026-01-01", "reported_at": "2026-01-04"}
    base.update(over)
    return base


# -- validation ---------------------------------------------------------


def test_validate_requires_core_fields():
    bad = shortage.validate_record({"kind": "recall", "tier": 9})
    rules = {e["rule"] for e in bad["errors"]}
    assert {"dossier_id_required", "din_required", "kind_invalid",
            "tier_invalid", "anticipated_start_required"} <= rules


def test_tier3_requires_reason():
    bad = shortage.validate_record(_report(reason=""))
    assert not bad["valid"]
    assert "tier3_reason_required" in {e["rule"] for e in bad["errors"]}
    ok = shortage.validate_record(_report(tier=2, reason=""))
    assert ok["valid"] and ok["record"]["tier"] == 2


def test_anticipated_end_must_not_precede_start():
    bad = shortage.validate_record(_report(anticipated_end="2026-01-15"))
    assert "end_before_start" in {e["rule"] for e in bad["errors"]}
    ok = shortage.validate_record(_report(anticipated_end="2026-03-01"))
    assert ok["valid"] and ok["record"]["anticipated_end"] == "2026-03-01"


# -- report windows / is_late -------------------------------------------


def test_tier3_shortage_must_be_reported_within_5_days_of_awareness():
    ok = shortage.validate_record(_report(reported_at="2026-01-06"))
    view = shortage.with_status(ok["record"])
    assert view["report_deadline"] == "2026-01-06"
    assert view["is_late"] is False
    late = shortage.validate_record(_report(reported_at="2026-01-07"))
    assert shortage.with_status(late["record"])["is_late"] is True


def test_lower_tier_shortages_have_no_mandatory_window():
    ok = shortage.validate_record(_report(tier=1, reported_at="2026-06-01"))
    view = shortage.with_status(ok["record"])
    assert view["report_deadline"] is None
    assert view["is_late"] is False


def test_discontinuation_six_months_ahead_prong():
    ok = shortage.validate_record(_report(
        kind="discontinuation", tier=1, anticipated_start="2026-12-01",
        became_aware="2026-01-10", reported_at="2026-05-30"))
    view = shortage.with_status(ok["record"])
    assert view["report_deadline"] == "2026-06-01"
    assert view["is_late"] is False


def test_discontinuation_late_decision_gets_5_days_from_awareness():
    on_time = shortage.validate_record(_report(
        kind="discontinuation", tier=1, anticipated_start="2026-12-01",
        became_aware="2026-10-01", reported_at="2026-10-06"))
    view = shortage.with_status(on_time["record"])
    assert view["report_deadline"] == "2026-10-06"
    assert view["is_late"] is False
    late = shortage.validate_record(_report(
        kind="discontinuation", tier=1, anticipated_start="2026-12-01",
        became_aware="2026-10-01", reported_at="2026-10-07"))
    assert shortage.with_status(late["record"])["is_late"] is True


def test_unreported_record_goes_late_as_of_deadline_passing():
    rec = shortage.validate_record(_report(reported_at=""))["record"]
    assert rec["reported_at"] is None
    assert shortage.with_status(rec, "2026-01-06")["is_late"] is False
    assert shortage.with_status(rec, "2026-01-07")["is_late"] is True


# -- API ------------------------------------------------------------------


def test_report_and_list_via_api(client):
    r = client.post("/api/lifecycle/shortage", json=_report())
    assert r.status_code == 201 and r.json()["id"]
    client.post("/api/lifecycle/shortage",
                json=_report(dossier_id="e2", reported_at="2026-01-09"))
    got = client.get("/api/lifecycle/shortage",
                     params={"dossier_id": "e2", "as_of": "2026-01-10"}).json()
    assert got["count"] == 1
    assert got["reports"][0]["is_late"] is True
    assert got["reports"][0]["report_deadline"] == "2026-01-06"


def test_shortage_validation_422(client):
    r = client.post("/api/lifecycle/shortage",
                    json={"dossier_id": "e1", "kind": "shortage"})
    assert r.status_code == 422


# -- DEL linkage ----------------------------------------------------------


def test_del_linkage_record_and_get(client):
    r = client.post("/api/lifecycle/del",
                    json={"dossier_id": "e1", "del_number": "DEL-100234-A",
                          "sites": [" Mississauga fill/finish ", "",
                                    "Scarborough packaging"]})
    assert r.status_code == 201
    body = r.json()
    assert body["del_number"] == "DEL-100234-A"
    assert body["sites"] == ["Mississauga fill/finish",
                             "Scarborough packaging"]
    got = client.get("/api/lifecycle/del",
                     params={"dossier_id": "e1"}).json()
    assert got["count"] == 1 and got["links"][0]["id"]


def test_del_linkage_requires_number_422(client):
    r = client.post("/api/lifecycle/del", json={"dossier_id": "e1"})
    assert r.status_code == 422
