"""Comparative-evidence node prose must follow the dosage-form ROUTE (swarm).

The 5.3.1 (BE study) and 1.6 (CS-BE) nodes hard-coded a PK 'AUC/Cmax 90% CI'
requirement even when the dosage form's route is a biowaiver or a topical
clinical/in-vitro comparison — contradicting the tool's own comparative_evidence
route. And 5.3.5 was force-na for every ANDS, foreclosing the comparative-
CLINICAL-endpoint arm a locally-acting topical generic needs.  [gaps 10, 11, 23]
"""

from app import section_tree


def _node(df, section, st="ANDS"):
    tree = section_tree.section_tree(submission_type=st, dosage_form_class=df)
    return next(n for m in tree["modules"] for n in m["nodes"]
               if n["section"] == section)


def test_solid_oral_531_keeps_the_pk_be_framing():
    assert "90%" in _node("ir_solid_oral", "5.3.1")["guidance"]


def test_topical_531_does_not_assert_a_pk_be_study():
    g = _node("topical_local", "5.3.1")["guidance"].lower()
    assert "90% ci" not in g and "cmax" not in g
    assert "clinical" in g or "in-vitro" in g


def test_parenteral_531_reflects_the_biowaiver_route():
    g = _node("parenteral_solution", "5.3.1")["guidance"].lower()
    assert "biowaiver" in g and "90% ci" not in g


def test_topical_535_is_a_conditional_clinical_arm_not_na():
    # the comparative-clinical-endpoint arm for a locally-acting topical lives in
    # 5.3.5 — it must be reachable (conditional), not hard na
    assert _node("topical_local", "5.3.5")["applicability"] == "conditional"


def test_solid_oral_535_stays_na_for_ands():
    assert _node("ir_solid_oral", "5.3.5")["applicability"] == "na"
