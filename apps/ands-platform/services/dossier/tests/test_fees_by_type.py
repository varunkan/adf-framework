"""Submission-type-aware review fee (swarm MATERIAL_ERROR cluster).

The tool charged the ANDS 'comparative-studies' review fee (~$71,953) to EVERY
submission type. HC Schedule 1 (Fees Order) puts a new-active-substance NDS in a
distinct higher grouping and a DIN (no supporting data) in a distinct lower one;
the comparative-studies grouping is only for a drug relying on comparative
studies (an ANDS). Emitting the wrong concrete fee is a MATERIAL_ERROR. The
honest fix: compute it ONLY for an ANDS; for other types state the correct
grouping and refer to HC Schedule 1 rather than a wrong number.  [gaps 1,3,5,14,20]
"""

from app import fees


def test_ands_review_fee_is_computed():
    r = fees.review_fee("2026-06-01", "ANDS")
    assert r["computed"] is True
    assert r["amount"] and r["amount"] > 0
    assert "comparative" in r["basis"].lower()


def test_nds_fee_is_not_the_comparative_studies_number():
    r = fees.review_fee("2026-06-01", "NDS")
    assert r["computed"] is False
    assert r["amount"] is None                    # no wrong concrete fee stated
    assert "Schedule 1" in r["basis"]
    assert "active substance" in r["basis"].lower()


def test_din_fee_refers_to_schedule_1_not_the_ands_fee():
    r = fees.review_fee("2026-06-01", "DIN")
    assert r["computed"] is False and r["amount"] is None
    assert "Schedule 1" in r["basis"]


def test_supplements_are_change_dependent_not_a_flat_top_fee():
    for st in ("SANDS", "SNDS"):
        r = fees.review_fee("2026-06-01", st)
        assert r["computed"] is False and r["amount"] is None, st


# -- content_state emits the right thing -------------------------------------
_P = "/api/dossier"


def test_content_state_nds_does_not_state_the_ands_fee(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e930201",
                "title": "nds", "submission_type": "NDS"})
    fees_block = client.get(f"{_P}/dossiers/e930201/content").json()["fees"]
    assert fees_block["review_fee"]["computed"] is False
    assert fees_block["review_fee"]["amount"] is None
    assert fees_block["mitigation"] is None       # no mitigation on an uncomputed fee


def test_content_state_ands_still_computes_the_fee(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e930202",
                "title": "ands", "submission_type": "ANDS"})
    fees_block = client.get(f"{_P}/dossiers/e930202/content").json()["fees"]
    assert fees_block["review_fee"]["computed"] is True
    assert fees_block["review_fee"]["amount"] > 0
