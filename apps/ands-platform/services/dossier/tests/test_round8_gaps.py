"""Round-8 swarm gaps — Right-to-Sell fee tiering, Form V guidance, biosimilar
SNDS pathway, SANDS fee grouping.

Web-verified vs canada.ca:
- e970008 MATERIAL: the annual Right-to-Sell fee is tiered (2026-27: prescription
  $5,626 / non-prescription $3,391 / disinfectant $1,760); a non-prescription DIN
  must be quoted the non-prescription tier, not the prescription figure.
- e970005 MINOR: Form V (s.5 PM(NOC)) is CONTENT-triggered, not submission-type
  triggered — the 1.2.4 na guidance must not state it "does not apply to a NDS".
- e970006 ENHANCEMENT: a biosimilar files an NDS OR SNDS (case-by-case) — the
  biosimilar scope note omitted SNDS.
- e970007 ENHANCEMENT: the SANDS review-fee note named no HC fee grouping.
"""

from app import fees, section_tree, product_scope

_P = "/api/dossier"


# ---- e970008: Right-to-Sell fee tiers by drug type --------------------------
def test_right_to_sell_tiers_by_drug_type():
    assert fees.right_to_sell("2026-07-09", drug_type="prescription")["amount"] == 5626.0
    assert fees.right_to_sell("2026-07-09", drug_type="non_prescription")["amount"] == 3391.0
    assert fees.right_to_sell("2026-07-09", drug_type="disinfectant")["amount"] == 1760.0


def test_right_to_sell_defaults_to_prescription():
    # backward-compat: no drug_type keeps the prescription figure
    assert fees.right_to_sell("2026-07-09")["amount"] == 5626.0


def test_non_prescription_din_content_state_uses_non_rx_tier(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e980801", "title": "Antacid",
                "submission_type": "DIN", "din_type": "category_iv",
                "product_class": "small_molecule"})
    rts = client.get(f"{_P}/dossiers/e980801/content").json()["fees"]["right_to_sell"]
    assert rts["amount"] == 3391.0
    assert rts.get("drug_type") == "non_prescription"


def test_prescription_default_content_state_keeps_rx_tier(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e980802", "title": "Rx generic",
                "submission_type": "ANDS", "dosage_form_class": "ir_solid_oral",
                "product_class": "small_molecule"})
    rts = client.get(f"{_P}/dossiers/e980802/content").json()["fees"]["right_to_sell"]
    assert rts["amount"] == 5626.0


# ---- e970005: Form V (1.2.4) na guidance is content-triggered ----------------
def _node(section, st):
    return next(x for m in section_tree.section_tree(submission_type=st)["modules"]
                for x in m["nodes"] if x["section"] == section)


def test_form_v_na_guidance_not_type_categorical():
    n = _node("1.2.4", "NDS")
    assert n["applicability"] == "na"           # NCE first NDS references nothing
    g = n["guidance"].lower()
    assert "does not apply to a nds" not in g   # no categorical type statement
    assert "compare" in g or "reference" in g or "pm(noc)" in g


# ---- e970006: biosimilar scope note names the SNDS pathway -------------------
def test_biosimilar_scope_note_names_snds():
    assert "SNDS" in product_scope.note("biosimilar")


# ---- e970007: SANDS review-fee note names the HC fee groupings ---------------
def test_sands_review_fee_names_the_two_groupings():
    basis = fees.review_fee("2026-07-09", "SANDS")["basis"].lower()
    assert "comparative" in basis
    assert "cmc" in basis or "pharmaceutical equivalence" in basis
