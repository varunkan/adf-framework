"""Round-4 swarm gaps — CTD-consistency + guidance refinements (all MAJOR/MINOR)."""

from app import section_tree
from app import special_pathways as sp


def _node(section, st="ANDS", **kw):
    tree = section_tree.section_tree(submission_type=st, **kw)
    return next(n for m in tree["modules"] for n in m["nodes"]
               if n["section"] == section)


# [1] OIP: 2.5/2.7 reachable so the 5.3.5 clinical/PD report has a summary home
def test_oip_clinical_summaries_are_conditional_not_suppressed():
    for sec in ("2.5", "2.7"):
        assert _node(sec, dosage_form_class="orally_inhaled")["applicability"] == "conditional", sec


def test_solid_oral_clinical_summaries_still_suppressed():
    for sec in ("2.5", "2.7"):
        assert _node(sec, dosage_form_class="ir_solid_oral")["applicability"] == "suppressed", sec


# [9] complex parenteral: clinical arms reachable (promises "comparative clinical")
def test_complex_parenteral_clinical_arms_reachable():
    assert _node("5.3.5", dosage_form_class="complex_parenteral")["applicability"] == "conditional"
    assert _node("2.7", dosage_form_class="complex_parenteral")["applicability"] == "conditional"


# [3] biosimilar NDS Form V is conditional (PM(NOC) s.5), not hard na
def test_biosimilar_nds_form_v_is_conditional():
    n = _node("1.2.4", st="NDS", product_in_scope=False)
    assert n["applicability"] == "conditional"


def test_innovator_small_molecule_nds_form_v_stays_na():
    n = _node("1.2.4", st="NDS", product_in_scope=True)
    assert n["applicability"] == "na"


# [4] DIN fees guidance does not claim "the ANDS review fee"
def test_din_fees_guidance_not_ands_specific():
    g = _node("1.2.2", st="DIN")["guidance"]
    assert "ANDS review fee" not in g and "Schedule 1" in g


# [5][8] na generic-only sections carry neutral 'not applicable' guidance for DIN
def test_din_na_generic_sections_have_neutral_guidance():
    for sec in ("1.6", "5.3.1", "1.2.4"):
        n = _node(sec, st="DIN")
        assert n["applicability"] == "na"
        assert "not apply" in n["guidance"].lower()


# [2] OIP quality nodes name the comparative in-vitro data (APSD / delivered dose)
def test_oip_quality_guidance_names_apsd_and_delivered_dose():
    g = _node("3.2.P.5", dosage_form_class="orally_inhaled")["guidance"].lower()
    assert "apsd" in g or "particle size" in g
    assert "delivered dose" in g


# [6] controlled_substance is a recognised special-pathway advisory
def test_controlled_substance_special_pathway_advisory():
    a = sp.advisory("controlled_substance")
    assert a and "CDSA" in a["summary"]


# [7] SANDS carries a scope_note
def test_sands_has_a_scope_note():
    tree = section_tree.section_tree(submission_type="SANDS")
    assert tree["scope_note"] and "change" in tree["scope_note"].lower()
