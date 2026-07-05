"""FORMS-PM — Product Monograph 1.3.1 as a rich bilingual FORM driving the
XML PM builder. Proves: the form schema covers Part I (Health Professional
Information) + Part III (Patient Medication Information), the ``pm_xml``
generator maps a filled PM form to a VALID bilingual XML PM (via
:func:`pm_xml.build_monograph_xml`) AND a readable PDF, and 1.3.1 is wired in
the section tree with the generate affordance while keeping upload. RED->GREEN.
"""

from app import form_schemas, generators, pm_xml, section_tree


# --- (1) a rich PM form schema covering Part I + Part III -------------------

def _pm_schema():
    return form_schemas.form_schema("1.3.1")


def test_pm_schema_uses_pm_xml_generator():
    schema = _pm_schema()
    assert schema is not None
    assert schema["generator"] == "pm_xml"
    assert schema["section"] == "1.3.1"
    assert schema["fields"], "the PM form must declare fields"


def test_pm_schema_covers_part_i_health_professional_information():
    names = {f["name"] for f in _pm_schema()["fields"]}
    # the real HC PM Part I structure — Health Professional Information
    for expected in ("proper_name", "brand_name", "din",
                     "therapeutic_classification", "indications",
                     "contraindications", "serious_warnings",
                     "dosage_administration", "adverse_reactions",
                     "drug_interactions", "action_clinical_pharmacology",
                     "storage_stability", "dosage_forms_composition"):
        assert expected in names, f"Part I field missing: {expected}"


def test_pm_schema_covers_part_iii_patient_medication_information():
    names = {f["name"] for f in _pm_schema()["fields"]}
    for expected in ("pmi_what_it_is_for", "pmi_how_to_take",
                     "pmi_warnings", "pmi_side_effects"):
        assert expected in names, f"Part III (PMI) field missing: {expected}"


def test_pm_prose_parts_are_ai_draftable():
    prose = set(form_schemas.prose_fields("1.3.1"))
    # every clinical narrative + PMI part must be AI-draftable
    for p in ("indications", "contraindications", "serious_warnings",
              "dosage_administration", "adverse_reactions",
              "action_clinical_pharmacology",
              "pmi_what_it_is_for", "pmi_how_to_take", "pmi_side_effects"):
        assert p in prose, f"{p} should be prose:true (AI-draftable)"


def test_pm_clinical_narratives_are_bilingual():
    fields = {f["name"]: f for f in _pm_schema()["fields"]}
    for name in ("indications", "contraindications", "dosage_administration",
                 "pmi_what_it_is_for"):
        assert fields[name].get("bilingual") is True, f"{name} must be bilingual"


def test_pm_schema_conforms_to_the_shared_contract():
    _TYPES = {"text", "textarea", "date", "select", "email", "number"}
    for f in _pm_schema()["fields"]:
        assert set(f) >= {"name", "label", "type", "required", "prose", "help"}
        assert f["type"] in _TYPES
        assert isinstance(f["required"], bool)
        assert isinstance(f["prose"], bool)
        assert f["help"], f"{f['name']} missing HC help one-liner"


# --- (2) the pm_xml generator: filled form -> valid XML PM + a PDF ----------

def _filled_pm_form():
    return {
        "proper_name": "Metformin hydrochloride",
        "brand_name": "Drugazole",
        "din": "02431234",
        "therapeutic_classification": "Oral antihyperglycemic agent",
        "indications": "For the management of type 2 diabetes mellitus.",
        "indications_fr": "Pour la prise en charge du diabete de type 2.",
        "contraindications": "Renal impairment; metabolic acidosis.",
        "contraindications_fr": "Insuffisance renale; acidose metabolique.",
        "serious_warnings": "Lactic acidosis — rare but serious.",
        "dosage_administration": "500 mg twice daily with meals.",
        "dosage_administration_fr": "500 mg deux fois par jour aux repas.",
        "adverse_reactions": "GI upset, diarrhea, nausea.",
        "drug_interactions": "Caution with cationic drugs.",
        "action_clinical_pharmacology": "Decreases hepatic glucose production.",
        "storage_stability": "Store at 15-30 C.",
        "dosage_forms_composition": "500 mg film-coated tablet.",
        "pmi_what_it_is_for": "This medicine lowers high blood sugar.",
        "pmi_what_it_is_for_fr": "Ce medicament abaisse la glycemie elevee.",
        "pmi_how_to_take": "Take with food as directed by your doctor.",
        "pmi_warnings": "Tell your doctor about kidney problems.",
        "pmi_side_effects": "Upset stomach and diarrhea are common.",
    }


def test_pm_xml_generator_produces_valid_xml_and_pdf():
    ctx = {"section": "1.3.1", "lang": "en", "form": _filled_pm_form()}
    doc = generators.generate("pm_xml", ctx)
    # two artifacts: the XML PM AND a readable PDF rendering
    artifacts = doc["artifacts"]
    kinds = {a["content_type"] for a in artifacts}
    assert "application/xml" in kinds
    assert "application/pdf" in kinds
    xml = next(a for a in artifacts if a["content_type"] == "application/xml")
    # the XML validates against the pm_xml stylesheet package
    assert xml["validation"]["valid"] is True
    body = xml["body"].decode("utf-8")
    assert "<product-monograph" in body
    # grounded HC content is carried through, not filler: the brand name is the
    # product-name, and a clinical narrative + its French translation are there
    assert "Drugazole" in body
    assert "type 2 diabetes" in body and "diabete de type 2" in body


def test_pm_xml_generator_maps_fields_to_controlled_section_codes():
    ctx = {"section": "1.3.1", "lang": "en", "form": _filled_pm_form()}
    doc = generators.generate("pm_xml", ctx)
    xml = next(a for a in doc["artifacts"]
               if a["content_type"] == "application/xml")["body"].decode("utf-8")
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    codes = {s.get("code") for s in root.findall("section")}
    # sections map to the pm_xml controlled vocabulary (no uncontrolled codes)
    assert codes <= set(pm_xml.PM_SECTION_CV)
    assert {"indications", "contraindications", "dosage",
            "patient-information"} <= codes


def test_pm_xml_generator_primary_body_is_the_xml():
    # the top-level doc dict is a valid document the store can persist:
    # the XML is the primary artifact (the mandated machine-readable PM).
    doc = generators.generate(
        "pm_xml", {"section": "1.3.1", "lang": "en", "form": _filled_pm_form()})
    assert doc["content_type"] == "application/xml"
    assert doc["filename"].endswith(".xml")
    assert pm_xml.validate_monograph_xml(doc["body"].decode("utf-8"))["valid"]


def test_pm_xml_pdf_carries_draft_watermark():
    doc = generators.generate(
        "pm_xml", {"section": "1.3.1", "lang": "en", "form": _filled_pm_form()})
    pdf = next(a for a in doc["artifacts"]
               if a["content_type"] == "application/pdf")
    assert b"DRAFT generated by ANDS Studio" in pdf["body"]
    assert pdf["body"].startswith(b"%PDF-")


def test_pm_xml_generator_required_fields_missing_still_builds_but_flags():
    # brand/proper name + DIN drive required XML elements; missing them keeps
    # the generator honest — the XML is built but validation reports the gap.
    doc = generators.generate("pm_xml",
                              {"section": "1.3.1", "lang": "en", "form": {}})
    xml = next(a for a in doc["artifacts"]
               if a["content_type"] == "application/xml")
    assert xml["validation"]["valid"] is False
    rules = {f["rule"] for f in xml["validation"]["findings"]}
    assert "pm_product_name_required" in rules


# --- (3) section-tree wiring: 1.3.1 generate + upload preserved -------------

def test_section_tree_1_3_1_wired_to_pm_xml_generator():
    n = section_tree.node_for("1.3.1")
    assert n["generator_key"] == "pm_xml"
    assert "generate" in n["affordances"]
    assert "upload" in n["affordances"]      # upload preserved
    assert n["bilingual"] is True


def test_pm_xml_no_longer_in_upload_only_by_design():
    # 1.3.1 now exposes generate like every other content section
    assert "generate" in section_tree.node_for("1.3.1")["affordances"]
