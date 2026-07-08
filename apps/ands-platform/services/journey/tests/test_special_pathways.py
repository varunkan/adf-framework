"""Special submission pathways — honest, cited, advisory-only (Tier C).

These are real Health Canada pathways/attributes a filer must consider when
PLANNING a submission (Priority Review, NOC/c, pediatric, controlled substances,
CTA, fixed-dose combination, complex generic). ANDS Studio RECOGNISES and
explains each with an HC citation, but does NOT automate its mechanics (e.g. it
does not run the Priority Review clock or track NOC/c conditions) — every entry
is honestly marked advisory. No hallucinated rules.
"""

from app import special_pathways as sp


def test_priority_review_carries_the_verified_180_vs_300_day_fact():
    p = sp.pathway("priority_review")
    assert p is not None
    assert "180" in p["summary"] and "300" in p["summary"]
    assert p["advisory_only"] is True
    assert p["citation"]


def test_noc_c_is_about_promising_evidence_and_confirmatory_trials():
    p = sp.pathway("noc_c")
    blob = (p["summary"] + " " + p["eligibility"]).lower()
    assert "promising" in blob
    assert "confirmatory" in blob
    assert p["citation"]


def test_controlled_substance_points_to_ocs_obligations():
    p = sp.pathway("controlled_substance")
    blob = p["summary"] + " " + p["eligibility"]
    assert "OCS" in blob or "Office of Controlled Substances" in blob
    assert p["advisory_only"] is True


def test_every_pathway_is_honest_advisory_with_a_citation():
    ids = {p["id"] for p in sp.list_pathways()}
    assert {"priority_review", "noc_c", "pediatric", "controlled_substance",
            "cta", "fixed_dose_combination", "complex_generic"} <= ids
    for p in sp.list_pathways():
        assert p["advisory_only"] is True, p["id"]
        assert p["citation"], p["id"]
        assert p["summary"] and p["label"] and p["kind"], p["id"]


def test_unknown_pathway_is_none():
    assert sp.pathway("teleport") is None


def test_noc_c_eligibility_names_severely_debilitating_and_unmet_need():  # r3 gap 6
    p = sp.pathway("noc_c")
    e = p["eligibility"].lower()
    assert "severely debilitating" in e
    assert "unmet" in e or "significant improvement" in e
