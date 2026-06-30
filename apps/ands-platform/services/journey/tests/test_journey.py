"""The gated journey spine — pure (ported from the monolith, decoupled)."""

from app import journey


def test_new_journey_orient_current_rest_locked():
    j = journey.journey({})
    by_key = {s["key"]: s for s in j["stages"]}
    assert by_key["orient"]["status"] == "current"
    assert by_key["company"]["status"] == "locked"
    # a locked stage names its precise unmet prerequisite + where to fix it
    gate = by_key["company"]["gate"]
    assert gate["needs_key"] == "orient"
    assert "Get oriented" in gate["reason"]
    assert by_key["company"]["next_label"] == "Get your product's file number"


def test_linear_gating_advances_one_step_at_a_time():
    # orient done (oriented flag) -> company becomes current, dossier still locked
    stages = {s["key"]: s for s in journey.stages({"oriented": True})}
    assert stages["company"]["status"] == "current"
    assert stages["dossier"]["status"] == "locked"
    # company done -> dossier current
    stages = {s["key"]: s for s in journey.stages({"company_id": "12345"})}
    assert stages["company"]["status"] == "done"
    assert stages["dossier"]["status"] == "current"


def test_company_id_implies_oriented():
    # a visible move past orientation (a Company ID exists) completes orient
    stages = {s["key"]: s for s in journey.stages({"company_id": "12345"})}
    assert stages["orient"]["status"] == "done"


def test_validation_gate_requires_zero_errors():
    base = {"company_id": "1", "dossier_id": "e123456", "applicant": "A",
            "drug_product": "D", "content_done": True}
    with_errors = {**base, "validation": {"ran": True, "errors": 3}}
    stages = {s["key"]: s for s in journey.stages(with_errors)}
    assert stages["validate"]["status"] == "current"   # not done — errors remain
    clean = {**base, "validation": {"ran": True, "errors": 0}}
    stages = {s["key"]: s for s in journey.stages(clean)}
    assert stages["validate"]["status"] == "done"
    assert stages["fees"]["status"] == "current"


def test_track_is_current_only_once_transmitted():
    stages = {s["key"]: s for s in journey.stages({})}
    assert stages["track"]["status"] == "locked"
    sent = {"company_id": "1", "dossier_id": "e1", "applicant": "A",
            "drug_product": "D", "content_done": True,
            "validation": {"ran": True, "errors": 0}, "fees": {"paid": True},
            "reviews": {"approved": True}, "esign": {"signed": True},
            "transmission": {"state": "SUBMITTED"}}
    pos = journey.position(sent)
    assert pos["transmitted"] is True and pos["complete"] is True
    assert pos["percent"] == 100


def test_position_percent_progresses():
    assert journey.position({})["percent"] == 0
    half = {"oriented": True, "company_id": "1", "dossier_id": "e1",
            "applicant": "A", "drug_product": "D", "content_done": True}
    # orient, company, dossier, submission, content done = 5 of 10
    assert journey.position(half)["done"] == 5
    assert journey.position(half)["percent"] == 50
