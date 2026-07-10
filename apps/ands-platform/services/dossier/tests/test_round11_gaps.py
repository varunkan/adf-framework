"""Round-11 swarm gaps — fee dates/groupings, small-business thresholds, topical
routing robustness, radiopharm-DIN conflict, DIN wording, 5.3.7 decouple, PR cue.

Web-verified vs canada.ca.
"""
from app import fees, section_tree, service
from app import comparative_evidence as ce

_P = "/api/dossier"


def _node(section, st="ANDS", **kw):
    t = section_tree.section_tree(submission_type=st, **kw)
    return next((n for m in t["modules"] for n in m["nodes"] if n["section"] == section), None)


# --- e970002/05/07/09/13: Right-to-Sell "due Oct 1" mislabels the payment date --
def test_rts_note_does_not_call_oct1_the_payment_due():
    r = fees.right_to_sell("2026-07-09", drug_type="prescription")
    assert "due Oct 1" not in r["note"]
    assert "30 days" in r["note"]
    assert r.get("invoice_date") == "2026-10-01"
    assert r.get("payment_due_date")  # ~30 days after Oct 1


# --- e970006/11: review_fee must not label every NDS "new active substance" ------
def test_biosimilar_nds_fee_not_new_active_substance():
    b = fees.review_fee("2026-07-09", "NDS", product_class="biosimilar")["basis"].lower()
    assert "new active substance" not in b
    assert "biosimilar" in b or "comparability" in b or "biologic" in b


def test_nds_fee_presents_nas_vs_non_nas():
    b = fees.review_fee("2026-07-09", "NDS")["basis"].lower()
    # names NAS as ONE grouping, not an assertion that this submission IS a NAS
    assert "new active substance" in b
    assert "without" in b or "non-nas" in b or "existing" in b or "lower" in b


# --- e970003: small-business eligibility thresholds (MATERIAL) --------------------
def test_small_business_thresholds_corrected():
    g = _node("1.2.2", st="ANDS")["guidance"].lower()
    assert "100 employee" in g or "fewer than 100" in g
    assert "30,000" in g or "30000" in g
    assert "5 million" in g or "$5" in g
    assert "300 staff" not in g and "100m" not in g


# --- e970003: 5.3.7 CRFs decoupled from 5.3.5's SABA "required" -------------------
def test_saba_537_not_gate_blocking_required():
    saba = dict(st="ANDS", dosage_form_class="orally_inhaled", drug_name="Salbutamol sulfate MDI")
    assert _node("5.3.7", **saba)["applicability"] != "required"
    assert _node("5.3.5", **saba)["applicability"] == "required"  # the PD study stays required


# --- e970004: topical mischaracterized as systemic PK (MATERIAL/MAJOR) ------------
def test_topical_semisolid_routes_to_clinical_not_systemic_pk():
    r = ce.route("topical_semisolid")
    assert r["route"] == "topical_clinical_invitro"
    assert r["requires_be_study"] is False


def test_topical_local_535_conditional():
    assert _node("5.3.5", st="ANDS", dosage_form_class="topical_local")["applicability"] == "conditional"


# --- e970008: din_type_note antacid belongs to labelling standard ----------------
def test_category_iv_note_redirects_antacid_to_labelling_standard():
    civ = service._din_type_note("category_iv").lower()
    assert "e.g. an antacid" not in civ            # not listed as a Category IV example
    assert "labelling standard" in civ             # redirected
    assert "antacid" in service._din_type_note("labelling_standard").lower()


# --- e970008: 1.3 Product Information group not a "bilingual PM" for a DIN --------
def test_din_13_group_purpose_is_label_not_pm_vehicle():
    p = _node("1.3", st="DIN")["purpose"].lower()
    assert "bilingual product monograph" not in p  # PM is not the DIN's info vehicle
    assert "label" in p and "no product monograph" in p


# --- e970005: scope_note Form V wording reconciled with na render ----------------
def test_nds_scope_note_form_v_not_flatly_conditional():
    sn = section_tree.section_tree(submission_type="NDS")["scope_note"].lower()
    assert "shown as conditional, not never" not in sn


# ---------- service-level (client) ----------
# --- e970012: DIN + out-of-core product class rejected at create (MATERIAL) -------
def test_radiopharm_din_rejected_at_create(client):
    r = client.post(f"{_P}/dossiers", json={"dossier_id": "e961201", "title": "Radiopharm diag",
                    "submission_type": "DIN", "product_class": "radiopharmaceutical"})
    assert r.status_code == 422
    assert "NDS" in (r.json().get("detail", "") + r.json().get("title", ""))


# --- e970010: Priority Review cover-letter cue on node 1.0 (ENHANCEMENT) ----------
def test_priority_review_cover_letter_cue(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e961002", "title": "PR drug",
                "submission_type": "NDS", "special_pathways": ["priority_review"]})
    cs = client.get(f"{_P}/dossiers/e961002/content").json()
    n10 = next(n for m in cs["modules"] for n in m["nodes"] if n["section"] == "1.0")
    assert "priority review" in n10["guidance"].lower()
