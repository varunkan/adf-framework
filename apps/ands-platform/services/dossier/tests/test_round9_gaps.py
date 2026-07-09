"""Round-9 swarm gaps — second-entry SABA MDI PD requirement + NOC/c advisory
completeness.

Web-verified vs canada.ca:
- e970003 MAJOR: HC "Guidance to Establish Equivalence ... Second Entry Short-
  Acting Beta2-Agonist MDI" (1999) — systemic absorption does not reflect airway
  effect, so PK bioequivalence is NOT sufficient for a SABA; a comparative
  PHARMACODYNAMIC clinical study is effectively REQUIRED. The tool understated it
  as "typically" and cited only the general 2020 OIP PK guidance.
- e970010 MINOR/ENH: the NOC/c advisory omitted the sponsor's cover-letter
  eligibility declaration + the Qualifying Notice (QN) step, and the downstream
  SNDS-C confirmatory-results filing that lifts the conditions to a full NOC.
"""

from app import section_tree
from app import comparative_evidence as ce
from app import special_pathways as sp

_P = "/api/dossier"


def _node(section, st="ANDS", **kw):
    tree = section_tree.section_tree(submission_type=st, **kw)
    return next((n for m in tree["modules"] for n in m["nodes"]
                 if n["section"] == section), None)


# ---- e970003: SABA MDI comparative-evidence route ---------------------------
def test_ce_route_saba_elevates_pd_and_cites_1999():
    r = ce.route("orally_inhaled", drug_name="Salbutamol sulfate 100 mcg MDI")
    assert r["requires_be_study"] is True
    ev = r["evidence"].lower()
    assert "pharmacodynamic" in ev and "required" in ev
    assert "1999" in r["citation"]


def test_ce_route_non_saba_oip_unchanged():
    assert ce.route("orally_inhaled", drug_name="Fluticasone inhaler")["route"] == "oip_studies"
    assert ce.route("orally_inhaled")["route"] == "oip_studies"


def test_saba_535_is_required():
    assert _node("5.3.5", dosage_form_class="orally_inhaled",
                 drug_name="salbutamol")["applicability"] == "required"


def test_non_saba_oip_535_stays_conditional():
    assert _node("5.3.5", dosage_form_class="orally_inhaled",
                 drug_name="fluticasone")["applicability"] == "conditional"


def test_content_state_saba_comparative_evidence(client):
    client.post(f"{_P}/dossiers", json={
        "dossier_id": "e990901", "title": "Salbutamol sulfate 100 mcg MDI",
        "submission_type": "ANDS", "dosage_form_class": "orally_inhaled",
        "product_class": "small_molecule"})
    ceb = client.get(f"{_P}/dossiers/e990901/content").json()["comparative_evidence"]
    assert "1999" in ceb["citation"]
    assert "required" in ceb["evidence"].lower()


# ---- e970010: NOC/c advisory completeness -----------------------------------
def test_noc_c_advisory_names_cover_letter_qn_and_snds_c():
    low = sp.advisory("noc_c")["summary"].lower()
    assert "cover letter" in low
    assert "qualifying notice" in low or "(qn)" in low
    assert "snds-c" in low or "snds" in low
