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
