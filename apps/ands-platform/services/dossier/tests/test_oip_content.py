"""Orally-inhaled (and other non-solid-oral) content-model corrections (swarm).

 * 3.2.P.2 told every filer to justify a biowaiver 'per ICH M9' — ICH M9 is the
   BCS-based biowaiver for IMMEDIATE-RELEASE SOLID ORAL products only; it does
   not apply to an inhaled / parenteral / topical form.  [gap 8]
 * An orally-inhaled generic needs comparative clinical / PD evidence, but 5.3.5
   was hard-na for every ANDS, leaving nowhere to place it.  [gap 9]
"""

from app import section_tree


def _node(df, section, st="ANDS"):
    tree = section_tree.section_tree(submission_type=st, dosage_form_class=df)
    return next(n for m in tree["modules"] for n in m["nodes"]
               if n["section"] == section)


def test_solid_oral_keeps_the_ich_m9_biowaiver_mention():
    assert "M9" in _node("ir_solid_oral", "3.2.P.2")["guidance"]


def test_inhaled_does_not_recommend_an_ich_m9_biowaiver():
    g = _node("orally_inhaled", "3.2.P.2")["guidance"]
    # either no M9 mention, or an explicit 'does not apply' caveat
    assert "M9" not in g or "not apply" in g.lower() or "only" in g.lower()


def test_parenteral_does_not_recommend_ich_m9():
    g = _node("parenteral_solution", "3.2.P.2")["guidance"]
    assert "M9" not in g or "not apply" in g.lower() or "only" in g.lower()


def test_inhaled_ands_has_a_conditional_clinical_pd_arm():
    assert _node("orally_inhaled", "5.3.5")["applicability"] == "conditional"
