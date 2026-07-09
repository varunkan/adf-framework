"""Round-5 swarm gaps — NDS Module-2 guidance consistency + OIP 5.3.1 source link.

Both CONFIRMED, web-verified vs canada.ca:
- e970005 (MAJOR): NDS 2.4-2.7 applicability=required but guidance said "not
  required — suppressed on the CS-BE path" (a static generic-ANDS string that was
  never swapped by submission_type), contradicting the applicability + scope_note.
- e970003 (MINOR): the orally-inhaled (oip_studies) 5.3.1 node cites the OIP 2020
  guidance in its text but its source_url linked the general comparative-BA page.
"""

from app import section_tree


def _node(section, st="ANDS", **kw):
    tree = section_tree.section_tree(submission_type=st, **kw)
    return next(n for m in tree["modules"] for n in m["nodes"]
                if n["section"] == section)


# [e970005] NDS Module-2 summaries are REQUIRED — guidance must not carry the
# generic-ANDS "not required / suppressed on the CS-BE path" text.
def test_nds_module2_summaries_required_and_guidance_matches():
    for sec in ("2.4", "2.5", "2.6", "2.7"):
        n = _node(sec, st="NDS")
        assert n["applicability"] == "required", sec
        g = n["guidance"].lower()
        assert "not required" not in g, sec
        assert "suppressed" not in g, sec
        assert "required" in g, sec


def test_nds_module2_summaries_cite_comprehensive_summary_rule():
    # FDR C.08.005.1(1)(c) — the comprehensive-summary requirement behind 2.4-2.7
    for sec in ("2.4", "2.5", "2.6", "2.7"):
        assert "C.08.005.1" in _node(sec, st="NDS")["guidance"], sec


def test_generic_be_module2_summaries_still_suppressed():
    # a pure comparative-BE ANDS still suppresses the 2.x summaries (unchanged)
    for sec in ("2.4", "2.6"):
        n = _node(sec, st="ANDS", dosage_form_class="ir_solid_oral")
        assert n["applicability"] == "suppressed", sec
        assert "not required" in n["guidance"].lower(), sec


def test_generic_clinical_route_module2_summary_guidance_not_contradictory():
    # an OIP generic's 2.5/2.7 are conditional — guidance must not say "not required"
    for sec in ("2.5", "2.7"):
        n = _node(sec, st="ANDS", dosage_form_class="orally_inhaled")
        assert n["applicability"] == "conditional", sec
        assert "not required" not in n["guidance"].lower(), sec


# [e970005, adjacent] an SNDS (brand supplement) must not show the generic-ANDS
# "suppressed on the CS-BE path" text on its Module-2 summaries either.
def test_snds_module2_summary_guidance_not_generic_ands_text():
    for sec in ("2.4", "2.5", "2.6", "2.7"):
        g = _node(sec, st="SNDS")["guidance"].lower()
        assert "generic ands" not in g, sec
        assert "cs-be path" not in g, sec


# [e970003] OIP 5.3.1 source link points to the OIP 2020 guidance, not the
# generic conduct-analysis-comparative BE page.
def test_oip_531_source_url_points_to_oip_guidance():
    n = _node("5.3.1", st="ANDS", dosage_form_class="orally_inhaled")
    assert "orally-inhaled-products-2020" in n["source_url"]
    assert "conduct-analysis-comparative" not in n["source_url"]


def test_solid_oral_531_source_url_stays_general_comparative():
    # the pk_be_study route still points to the general comparative-BA page
    n = _node("5.3.1", st="ANDS", dosage_form_class="ir_solid_oral")
    assert "conduct-analysis-comparative" in n["source_url"]
