"""Round-10 swarm gaps — RTS-fee honesty when tier unknown, microsphere complex-
generic inference, Module-5 eCTD structure, scope_note Form V, NOC/c cover cue.

Web-verified vs canada.ca:
- e970008 MAJOR: right_to_sell asserted a concrete prescription-tier fee even when
  the tier-determining drug type is unknown (DIN with no sub-type), contradicting
  review_fee's honest deferral in the same payload — label it an estimate.
- e970013 MAJOR: a microsphere long-acting injectable declared parenteral_solution
  was silently routed as a simple aqueous-solution biowaiver; HC waives BE only for
  aqueous solutions, so a depot/microsphere is a complex generic (BE required).
- e970005 MINOR: Module 5 lacked 5.2 (Tabular Listing of All Clinical Studies) and
  5.3.7 (Case Report Forms) for an NDS.
- e970012 MINOR: the NDS scope_note flatly denied Form V, contradicting the
  conditional 1.2.4 (Form V is content-triggered — s.5 PM(NOC)).
- e970010 ENHANCEMENT: the 1.0 Cover Letter node carried no NOC/c declaration cue
  when the NOC/c pathway is active.
"""

from app import fees, section_tree
from app import comparative_evidence as ce

_P = "/api/dossier"


def _node(section, st="ANDS", **kw):
    t = section_tree.section_tree(submission_type=st, **kw)
    return next((n for m in t["modules"] for n in m["nodes"]
                 if n["section"] == section), None)


# ---- e970008: RTS honest when the tier is not confidently known -------------
def test_right_to_sell_estimated_flag():
    r = fees.right_to_sell("2026-07-09", drug_type="prescription", estimated=True)
    assert r["estimated"] is True
    assert "estimate" in r["note"].lower()


def test_rts_unset_din_is_estimated(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e900801",
                "title": "Unset DIN", "submission_type": "DIN"})
    rts = client.get(f"{_P}/dossiers/e900801/content").json()["fees"]["right_to_sell"]
    assert rts.get("estimated") is True


def test_rts_otc_din_is_confident(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e900802", "title": "Antacid",
                "submission_type": "DIN", "din_type": "category_iv"})
    rts = client.get(f"{_P}/dossiers/e900802/content").json()["fees"]["right_to_sell"]
    assert rts["amount"] == 3391.0
    assert not rts.get("estimated")


# ---- e970013: microsphere / depot parenteral is a complex generic -----------
def test_microsphere_parenteral_reroutes_to_complex_generic():
    r = ce.route("parenteral_solution",
                 drug_name="Leuprolide long-acting injectable microsphere depot")
    assert r["route"] == "complex_generic_pk"
    assert r["requires_be_study"] is True


def test_plain_aqueous_parenteral_still_biowaiver():
    r = ce.route("parenteral_solution", drug_name="Sodium chloride 0.9% injection")
    assert r["route"] == "parenteral_biowaiver"


def test_microsphere_531_required():
    n = _node("5.3.1", dosage_form_class="parenteral_solution",
              drug_name="microsphere depot suspension")
    assert n["applicability"] == "required"


# ---- e970005: Module 5 eCTD structure ---------------------------------------
def test_module5_has_tabular_listing_and_crfs():
    assert _node("5.2", st="NDS") is not None
    assert _node("5.3.7", st="NDS") is not None
    assert _node("5.3.7", st="NDS")["applicability"] == "required"
    assert _node("5.3.7", st="ANDS")["applicability"] == "na"


# ---- e970012: scope_note Form V is conditional ------------------------------
def test_nds_scope_note_form_v_not_flatly_denied():
    sn = section_tree.section_tree(submission_type="NDS")["scope_note"].lower()
    assert "no form v" not in sn
    assert "form v" in sn and ("only if" in sn or "patent register" in sn or "when" in sn)


# ---- e970010: NOC/c cover-letter cue on node 1.0 ----------------------------
def test_noc_c_cover_letter_cue(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e901001", "title": "NOCc drug",
                "submission_type": "NDS", "special_pathways": ["noc_c"]})
    cs = client.get(f"{_P}/dossiers/e901001/content").json()
    n10 = next(n for m in cs["modules"] for n in m["nodes"] if n["section"] == "1.0")
    g = n10["guidance"].lower()
    assert "noc/c" in g and "cover letter" in g
