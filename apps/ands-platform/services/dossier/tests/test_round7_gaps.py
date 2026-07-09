"""Round-7 swarm gaps — BE-ruleset date resolution, DIN three-way coding,
controlled-substance inference, restored-dossier pathway-conflict validation.

Web-verified vs canada.ca:
- e970001 MAJOR: ICH M13A is in force (effective 2025-12-27) — a post-cutover IR
  solid-oral ANDS BE study must comply with M13A; the "or legacy" hedge is wrong.
- e970008 MAJOR: HC codes DINA (labelling standard) and DINF (Category IV) as
  DISTINCT application types; a data-supported DINA is the CMC path. Three codings.
- e970011 MAJOR: an opioid/CDSA-scheduled product must surface the CDSA/OCS
  advisory by default, not silently default controlled_substance=false.
- e970006 MINOR: a restored legacy biosimilar+ANDS dossier must not report
  validation.passed=true for a combination intake forbids.
"""

from app import section_tree
from app import be_ruleset
from app import controlled_substances as cs

_P = "/api/dossier"


def _node(section, st="ANDS", **kw):
    tree = section_tree.section_tree(submission_type=st, **kw)
    return next((n for m in tree["modules"] for n in m["nodes"]
                 if n["section"] == section), None)


# ---- e970001: BE ruleset resolves to M13A for a post-cutover IR solid oral ----
def test_be_ruleset_resolves_m13a_after_cutover():
    rs = be_ruleset.resolve("2026-07-09", "ir_solid_oral")
    assert rs["version"] == "M13A"
    assert rs["effective"] == "2025-12-27"


def test_be_ruleset_legacy_before_cutover_or_non_ir():
    assert be_ruleset.resolve("2025-01-01", "ir_solid_oral")["version"] == "legacy"
    assert be_ruleset.resolve("2026-07-09", "mr_solid_oral")["version"] == "legacy"


def test_cs_be_guidance_names_m13a_and_drops_hedge_for_ir_solid_oral():
    n = _node("1.6", st="ANDS", dosage_form_class="ir_solid_oral", be_ruleset="M13A")
    g = n["guidance"]
    assert "M13A" in g
    assert "or legacy" not in g.lower()


def test_content_state_emits_be_ruleset_m13a(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e970701",
                "title": "Generic IR tablet", "submission_type": "ANDS",
                "dosage_form_class": "ir_solid_oral", "product_class": "small_molecule"})
    csx = client.get(f"{_P}/dossiers/e970701/content").json()
    assert csx.get("be_ruleset") and csx["be_ruleset"]["version"] == "M13A"
    n16 = next(n for m in csx["modules"] for n in m["nodes"] if n["section"] == "1.6")
    assert "or legacy" not in n16["guidance"].lower()


# ---- e970008: DIN three-way coding (DINA / DINA-LS / DINF) --------------------
def test_din_data_supported_requires_cmc():
    assert _node("3.2.S.1", st="DIN", din_type="data_supported")["applicability"] == "required"
    assert _node("2.3", st="DIN", din_type="data_supported")["applicability"] == "required"


def test_din_labelling_standard_and_category_iv_are_no_cmc():
    for dt in ("labelling_standard", "category_iv"):
        assert _node("3.2.S.1", st="DIN", din_type=dt)["applicability"] == "na", dt
        assert _node("2.3", st="DIN", din_type=dt)["applicability"] == "na", dt


def test_legacy_standard_referenced_still_maps_to_no_cmc():
    # round-6 value stays valid (existing dossiers) — still na
    assert _node("3.2.S.1", st="DIN", din_type="standard_referenced")["applicability"] == "na"


def test_din_pm_always_na_regardless_of_three_way():
    for dt in ("data_supported", "labelling_standard", "category_iv"):
        assert _node("1.3.1", st="DIN", din_type=dt)["applicability"] == "na", dt


def test_din_type_notes_name_dina_dinf_precisely(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e970702", "title": "Antacid",
                "submission_type": "DIN", "din_type": "category_iv"})
    note = client.get(f"{_P}/dossiers/e970702/content").json()["din_type_note"]
    assert "DINF" in note and "Category IV" in note
    client.post(f"{_P}/dossiers", json={"dossier_id": "e970703", "title": "ASA tab",
                "submission_type": "DIN", "din_type": "labelling_standard"})
    note2 = client.get(f"{_P}/dossiers/e970703/content").json()["din_type_note"]
    assert "labelling standard" in note2.lower() and "category iv" not in note2.lower()


# ---- e970011: controlled-substance inference from the product name -----------
def test_cs_detect_matches_opioid_keyword():
    assert cs.detect("Scheduled opioid analgesic (oxycodone) IR tablet")
    assert cs.detect("Plain acetaminophen tablet") is None


def test_content_state_infers_controlled_substance_for_opioid(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e970704",
                "title": "Oxycodone hydrochloride IR tablet", "submission_type": "NDS",
                "product_class": "small_molecule"})
    csx = client.get(f"{_P}/dossiers/e970704/content").json()
    assert csx.get("controlled_substance_inferred") is True
    assert csx.get("controlled_substance_note")
    assert "CDSA" in csx["controlled_substance_note"]


def test_no_false_inference_for_ordinary_drug(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e970705",
                "title": "Atorvastatin 20 mg tablet", "submission_type": "ANDS",
                "product_class": "small_molecule"})
    csx = client.get(f"{_P}/dossiers/e970705/content").json()
    assert not csx.get("controlled_substance_inferred")


# ---- e970006: restored/legacy forbidden combo fails validation --------------
def test_forbidden_combo_dossier_fails_validation(ctx):
    # insert a legacy biosimilar+ANDS row directly (bypassing the create guard)
    ctx.repo.create_dossier_index({
        "dossier_id": "e970706", "title": "Legacy biosimilar", "submission_type": "ANDS",
        "product_class": "biosimilar", "cs_be_only": True})
    csx = ctx.client.get(f"{_P}/dossiers/e970706/content").json()
    assert csx["validation"]["passed"] is False
    assert any("pathway" in (e.get("rule", "") + e.get("message", "")).lower()
               for e in csx["validation"]["errors"])
    assert csx["gate"]["complete"] is False
