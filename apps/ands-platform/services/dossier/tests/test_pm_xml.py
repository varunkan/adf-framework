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
