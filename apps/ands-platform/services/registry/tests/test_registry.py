"""Pure registration registry domain (REQ-111)."""

from app import registry


def test_new_registration_defaults_submitted():
    out = registry.new_registration({"product": "Metformin 500mg",
                                     "dossier_id": "e123456", "din": "02431234",
                                     "drug_type": "prescription"})
    assert out["valid"]
    assert out["registration"]["status"] == "Submitted"
    assert out["registration"]["country"] == "CA"


def test_new_registration_validation():
    out = registry.new_registration({"product": "", "dossier_id": "",
                                     "drug_type": "moon"})
    rules = {e["rule"] for e in out["errors"]}
    assert {"product_required", "dossier_id_required", "drug_type_invalid"} <= rules


def test_status_transitions():
    assert registry.validate_status_transition("Submitted", "NOC-Issued")["valid"]
    assert registry.validate_status_transition("NOC-Issued", "Marketed")["valid"]
    bad = registry.validate_status_transition("Cancelled", "Marketed")
    assert not bad["valid"] and bad["rule"] == "status_illegal_transition"
    unknown = registry.validate_status_transition("Submitted", "Zombie")
    assert unknown["rule"] == "status_unknown"


def test_right_to_sell_only_post_noc():
    submitted = {"status": "Submitted", "drug_type": "prescription"}
    assert registry.right_to_sell_obligation(submitted, "2025-09-15")["applies"] \
        is False
    marketed = {"status": "Marketed", "drug_type": "prescription",
                "din": "02431234"}
    ob = registry.right_to_sell_obligation(marketed, "2025-09-15")
    assert ob["applies"] and ob["due_date"] == "2025-10-01"
    assert ob["overdue"] is False
    assert registry.right_to_sell_obligation(marketed, "2025-11-01")["overdue"] \
        is True


# -- TIER-B: honest note for NNHPD-assessed disinfectant / biocide DINs --------
def test_disinfectant_registration_carries_an_honest_nnhpd_note():
    out = registry.new_registration({"product": "SaniClean surface disinfectant",
                                     "dossier_id": "e223456", "din": "02439999",
                                     "drug_type": "disinfectant"})
    assert out["valid"]
    note = out["registration"].get("regulatory_note")
    assert note and "NNHPD" in note
    # the honest boundary: a disinfectant DIN is NOT an ANDS/NDS eCTD review
    assert "ANDS" in note or "eCTD" in note


def test_biocide_registration_carries_an_honest_note():
    out = registry.new_registration({"product": "BioGuard biocide",
                                     "dossier_id": "e223457", "din": "02439998",
                                     "drug_type": "biocide"})
    assert out["valid"]
    note = out["registration"].get("regulatory_note")
    assert note and ("NNHPD" in note or "Biocides Regulations" in note)


def test_prescription_registration_has_no_scope_note():
    out = registry.new_registration({"product": "Metformin 500mg",
                                     "dossier_id": "e123456", "din": "02431234",
                                     "drug_type": "prescription"})
    assert out["valid"]
    assert out["registration"].get("regulatory_note") in (None, "")


def test_regulatory_note_is_public_helper():
    assert registry.regulatory_note("disinfectant")
    assert registry.regulatory_note("biocide")
    assert registry.regulatory_note("prescription") in (None, "")
    assert registry.regulatory_note("") in (None, "")
