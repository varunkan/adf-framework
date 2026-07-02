"""REQ-099 — XML Product Monograph builder/validator."""

from app import pm_xml


def _good_pm():
    return {"dossier_id": "e1", "lang": "en", "product_name": "Metformin 500mg",
            "din": "02431234",
            "sections": [{"code": "indications", "title": "Indications",
                          "text": "Type 2 diabetes."},
                         {"code": "dosage", "title": "Dosage", "text": "500mg BID"}]}


def test_build_then_validate_roundtrip():
    xml = pm_xml.build_monograph_xml(_good_pm())
    assert "<product-monograph" in xml and "Metformin" in xml
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is True and result["findings"] == []


def test_build_escapes_content():
    xml = pm_xml.build_monograph_xml({
        "product_name": "A & B <test>", "din": "1",
        "sections": [{"code": "indications", "title": "t", "text": "x"}]})
    assert "&amp;" in xml and "&lt;test&gt;" in xml   # auto-escaped, not raw
    assert pm_xml.validate_monograph_xml(xml)["valid"]


def test_validate_missing_required_blocks():
    xml = pm_xml.build_monograph_xml({"product_name": "", "din": "",
                                      "sections": []})
    result = pm_xml.validate_monograph_xml(xml)
    rules = {f["rule"] for f in result["findings"]}
    assert result["valid"] is False
    assert {"pm_product_name_required", "pm_din_required",
            "pm_sections_required"} <= rules


def test_validate_malformed_xml():
    result = pm_xml.validate_monograph_xml("<product-monograph><din>")
    assert result["valid"] is False
    assert result["findings"][0]["rule"] == "pm_xml_malformed"


def test_uncontrolled_section_code_is_warning_not_block():
    xml = pm_xml.build_monograph_xml({
        "product_name": "P", "din": "1",
        "sections": [{"code": "made-up", "title": "t", "text": "x"}]})
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is True   # warnings don't block
    assert any(f["rule"] == "pm_section_code_uncontrolled"
               for f in result["findings"])


def test_require_xml_pm_gate():
    assert pm_xml.require_xml_pm({"xml_pm_required": True,
                                  "has_xml_pm": False})["can_transmit"] is False
    assert pm_xml.require_xml_pm({"xml_pm_required": True,
                                  "has_xml_pm": True})["can_transmit"] is True
    assert pm_xml.require_xml_pm({"xml_pm_required": False})["can_transmit"] is True


# -- ported stylesheet-package validation (rep_stylesheet.py port) ----------

def test_entity_declarations_are_blocked():
    laughs = ('<?xml version="1.0"?><!DOCTYPE product-monograph ['
              '<!ENTITY a "ha"><!ENTITY b "&a;&a;">]>'
              '<product-monograph><din>&b;</din></product-monograph>')
    result = pm_xml.validate_monograph_xml(laughs)
    assert result["valid"] is False
    assert result["findings"][0]["rule"] == "pm_xml_entity_unsafe"


def test_build_stamps_active_stylesheet_version():
    xml = pm_xml.build_monograph_xml(_good_pm())
    assert (f'stylesheet-version="{pm_xml.active_stylesheet_version()}"'
            in xml)
    assert pm_xml.validate_monograph_xml(xml)["valid"] is True


def test_unmatched_stylesheet_version_blocks():
    xml = ('<product-monograph lang="en" stylesheet-version="1999-01-01">'
           '<product-name>P</product-name><din>1</din>'
           '<section code="dosage"><title>t</title><text>x</text></section>'
           '</product-monograph>')
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is False
    assert any(f["rule"] == "pm_stylesheet_version_unmatched"
               for f in result["findings"])


def test_missing_stylesheet_version_falls_back_to_active():
    xml = ('<product-monograph lang="en">'
           '<product-name>P</product-name><din>1</din>'
           '<section code="dosage"><title>t</title><text>x</text></section>'
           '</product-monograph>')
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is True
    assert not any(f["rule"] == "pm_stylesheet_version_unmatched"
                   for f in result["findings"])


def test_blank_section_fields_warn_not_block():
    xml = pm_xml.build_monograph_xml({
        "product_name": "P", "din": "1",
        "sections": [{"code": "dosage", "title": "", "text": ""}]})
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is True
    blanks = [f for f in result["findings"]
              if f["rule"] == "pm_section_blank_field"]
    assert {"title", "text"} == {f["field"] for f in blanks}


def test_duplicate_section_codes_warn():
    xml = pm_xml.build_monograph_xml({
        "product_name": "P", "din": "1",
        "sections": [{"code": "dosage", "title": "a", "text": "x"},
                     {"code": "dosage", "title": "b", "text": "y"}]})
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is True
    assert any(f["rule"] == "pm_section_code_duplicate"
               for f in result["findings"])


def test_uncontrolled_lang_warns():
    xml = pm_xml.build_monograph_xml(dict(_good_pm(), lang="de"))
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is True
    assert any(f["rule"] == "pm_lang_uncontrolled"
               for f in result["findings"])


def test_image_without_href_blocks():
    xml = ('<product-monograph lang="en">'
           '<product-name>P</product-name><din>1</din>'
           '<section code="dosage"><title>t</title><text>x</text></section>'
           '<image href=" "/></product-monograph>')
    result = pm_xml.validate_monograph_xml(xml)
    assert result["valid"] is False
    assert any(f["rule"] == "pm_image_href_required"
               for f in result["findings"])


def test_stylesheet_package_registry_is_versioned_data(monkeypatch):
    monkeypatch.setattr(pm_xml, "_STYLESHEET_PACKAGES",
                        dict(pm_xml._STYLESHEET_PACKAGES))
    assert pm_xml.active_stylesheet_version() == \
        pm_xml.BUNDLED_STYLESHEET_VERSION
    newer = pm_xml.load_stylesheet()
    newer["published"] = "2026-01-01"
    pm_xml.register_stylesheet_package("2026-01-01", newer)
    assert pm_xml.active_stylesheet_version() == "2026-01-01"
    # a doc stamped with the freshly registered edition now validates
    xml = pm_xml.build_monograph_xml(_good_pm())
    assert 'stylesheet-version="2026-01-01"' in xml
    assert pm_xml.validate_monograph_xml(xml)["valid"] is True


def test_load_unknown_stylesheet_version_raises():
    import pytest
    with pytest.raises(pm_xml.StylesheetVersionError):
        pm_xml.load_stylesheet("1999-01-01")


def test_loaded_stylesheet_is_a_defensive_copy():
    pkg = pm_xml.load_stylesheet()
    pkg["fields"].clear()
    assert pm_xml.load_stylesheet()["fields"]


# -- HC generic mandate-wave trigger (REQ-099 gate) --------------------------

def test_wave_table_innovators_first_and_flagged_estimates():
    waves = {w["wave"]: w for w in pm_xml.XML_PM_MANDATE_WAVES}
    assert waves["innovator"]["effective"] < waves["generic"]["effective"]
    for w in waves.values():   # never presented as HC-fixed (backbone.py style)
        assert w["estimate"] is True and w["hc_fixed"] is False


def test_generic_on_or_after_wave_requires_xml_pm():
    wave = [w for w in pm_xml.XML_PM_MANDATE_WAVES
            if w["wave"] == "generic"][0]
    gate = pm_xml.require_xml_pm({"pathway": "generic",
                                  "filing_date": wave["effective"],
                                  "has_xml_pm": False})
    assert gate["can_transmit"] is False
    blocker = gate["blockers"][0]
    assert blocker["rule"] == "xml_pm_mandate_wave"
    assert blocker["wave"] == "generic"
    assert blocker["estimate"] is True
    # with a validated XML PM in hand the same filing transmits
    assert pm_xml.require_xml_pm({"pathway": "ands",
                                  "filing_date": "2027-03-01",
                                  "has_xml_pm": True})["can_transmit"] is True


def test_generic_before_wave_is_not_required():
    assert pm_xml.require_xml_pm({"pathway": "generic",
                                  "filing_date": "2025-12-31",
                                  "has_xml_pm": False})["can_transmit"] is True


def test_innovator_wave_precedes_generics():
    assert pm_xml.require_xml_pm({"pathway": "nds",
                                  "filing_date": "2025-06-01",
                                  "has_xml_pm": False})["can_transmit"] is False
    assert pm_xml.require_xml_pm({"pathway": "innovator",
                                  "filing_date": "2024-12-31",
                                  "has_xml_pm": False})["can_transmit"] is True


def test_unknown_pathway_or_bad_date_never_triggers():
    assert pm_xml.require_xml_pm({"pathway": "otc",
                                  "filing_date": "2030-01-01"})["can_transmit"]
    assert pm_xml.require_xml_pm({"pathway": "generic",
                                  "filing_date": "soon"})["can_transmit"]
    assert pm_xml.require_xml_pm({"pathway": "generic"})["can_transmit"]


def test_explicit_flag_still_dominates():
    # explicit requirement keeps its original rule id and behaviour
    gate = pm_xml.require_xml_pm({"xml_pm_required": True,
                                  "has_xml_pm": False,
                                  "pathway": "generic",
                                  "filing_date": "2020-01-01"})
    assert gate["can_transmit"] is False
    assert gate["blockers"][0]["rule"] == "xml_pm_required"


def test_mandate_helper_direct():
    assert pm_xml.xml_pm_required_by_mandate("generic", "2027-01-01") is True
    assert pm_xml.xml_pm_required_by_mandate("generic", "2024-01-01") is False
    assert pm_xml.xml_pm_required_by_mandate("", "2027-01-01") is False


def test_pm_xml_api_build_and_validate(client):
    built = client.post("/api/dossier/monograph/xml/build",
                        json=_good_pm()).json()
    assert built["validation"]["valid"] is True
    v = client.post("/api/dossier/monograph/xml/validate",
                    json={"xml": built["xml"]})
    assert v.json()["valid"] is True
    gate = client.post("/api/dossier/monograph/xml/gate",
                       json={"xml_pm_required": True, "has_xml_pm": False})
    assert gate.json()["can_transmit"] is False
