"""Journey-side comparative-evidence routing (Tier A gap fix).

The gap: the 'tell me about your drug' engine always required a comparative BE
study (Module 5.3.1) for a generic, whatever the dosage form — so it never told
a filer of a parenteral/ophthalmic/oral aqueous solution that Health Canada may
WAIVE the in-vivo study, nor did it route orally-inhaled or topical forms to
their proper (non-PK) evidence. ``assess`` must surface the route + a biowaiver
advisory when one applies, without ever telling a solid-oral filer to skip BE.
"""

from app import drug_intake as di


def test_solid_oral_and_inhaled_require_a_be_study():
    for df in ("ir_solid_oral", "mr_solid_oral", "orally_inhaled", "other"):
        r = di.comparative_evidence_route(df)
        assert r["requires_be_study"] is True, df
        assert r["citation"] and r["evidence"]


def test_solutions_and_topical_open_a_biowaiver_route():
    for df in ("parenteral_solution", "oral_solution",
               "ophthalmic_otic_solution", "topical_local"):
        r = di.comparative_evidence_route(df)
        assert r["requires_be_study"] is False, df
        assert r["citation"]


def test_assess_surfaces_a_biowaiver_advisory_for_a_parenteral_solution():
    a = di.assess({"submission_type": "ANDS",
                   "dosage_form_class": "parenteral_solution"})
    ce = a["checks"]["comparative_evidence"]
    assert ce["requires_be_study"] is False
    rules = {adv["rule"] for adv in a["advisories"]}
    assert "comparative_evidence_biowaiver" in rules


def test_assess_does_not_offer_a_biowaiver_for_solid_oral():
    a = di.assess({"submission_type": "ANDS",
                   "dosage_form_class": "ir_solid_oral"})
    ce = a["checks"]["comparative_evidence"]
    assert ce["requires_be_study"] is True
    rules = {adv["rule"] for adv in a["advisories"]}
    assert "comparative_evidence_biowaiver" not in rules


def test_assess_still_evaluates_a_supplied_solid_oral_be_study():
    # regression: adding the route must not drop the existing BE evaluation
    a = di.assess({"submission_type": "ANDS",
                   "dosage_form_class": "ir_solid_oral",
                   "submission_date": "2025-06-01",
                   "be_study": {"auc": {"ci_lower": 90, "ci_upper": 110},
                                "cmax": {"point_estimate": 100}}})
    assert a["checks"]["bioequivalence"]["bioequivalent"] is True
