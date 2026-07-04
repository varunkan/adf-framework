"""The persistent READY/BLOCKED card derived from the journey spine."""

from app import readiness_card


def test_new_submission_is_blocked_with_current_blocker():
    c = readiness_card.card({})
    assert c["status"] == "BLOCKED"
    assert c["ready_to_file"] is False
    # the single thing to do next is named in plain language
    assert c["blocking_items"], "a blocked card must name what's blocking it"
    assert c["resume"]["key"] == "orient"    # the first action for a new filing


def test_ready_once_signed():
    signed = {"company_id": "1", "dossier_id": "e123456", "applicant": "A",
              "drug_product": "D", "content_done": True,
              "validation": {"ran": True, "errors": 0}, "fees": {"paid": True},
              "reviews": {"approved": True}, "esign": {"signed": True}}
    c = readiness_card.card(signed)
    assert c["status"] == "READY" and c["ready_to_file"] is True
    assert all(t["state"] == "pass" for t in c["tiles"])


def test_blocked_at_validation_lists_it():
    blocked = {"company_id": "1", "dossier_id": "e1", "applicant": "A",
               "drug_product": "D", "content_done": True,
               "validation": {"ran": True, "errors": 2}}
    c = readiness_card.card(blocked)
    assert c["status"] == "BLOCKED"
    assert c["resume"]["key"] == "validate"


# WS1-b (round-7 #1 blocker, ALL 24 respondents): READY must reflect a real,
# named eCTD-validation pass, not just step-completion. The card exposes a
# distinct `validation` tier so the badge's meaning is legible and honest.
def test_readiness_surfaces_validation_tier_not_yet_run():
    c = readiness_card.card({})
    assert "validation" in c
    assert c["validation"]["ran"] is False
    assert c["validation"]["passed"] is False


def test_readiness_validation_tier_passed_carries_criteria():
    signed = {"company_id": "1", "dossier_id": "e123456", "applicant": "A",
              "drug_product": "D", "content_done": True,
              "validation": {"ran": True, "errors": 0, "warnings": 2,
                             "checked": 30, "real": True,
                             "criteria": {"name": "ANDS Studio structural eCTD "
                                          "validator", "version": "1.2",
                                          "synced": "2026-05"}},
              "fees": {"paid": True}, "reviews": {"approved": True},
              "esign": {"signed": True}}
    v = readiness_card.card(signed)["validation"]
    assert v["ran"] and v["passed"] is True
    assert v["errors"] == 0 and v["warnings"] == 2 and v["checked"] == 30
    assert v["real"] is True and v["criteria"]["version"] == "1.2"


def test_readiness_validation_tier_failed_is_not_passed():
    v = readiness_card.card({"validation": {"ran": True, "errors": 3}})["validation"]
    assert v["ran"] is True and v["passed"] is False and v["errors"] == 3
