"""XML Product Monograph builder/validator (REQ-099) — pure, stdlib only.

Generates a structured XML Product Monograph (ElementTree auto-escapes content)
and validates it: well-formedness + required elements + section codes against a
controlled vocabulary. A transmit gate blocks a PDF-only PM where XML is required.
No lxml — mirrors how the monolith embeds XSD/CV as data.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

ROOT_TAG = "product-monograph"

# controlled vocabulary of PM section codes (a representative HC XML-PM subset)
PM_SECTION_CV = ("indications", "contraindications", "warnings", "dosage",
                 "adverse-reactions", "pharmacology", "storage", "supply",
                 "patient-information")


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def build_monograph_xml(pm_data: dict) -> str:
    """Build an XML Product Monograph from structured data (auto-escaped)."""
    pm_data = pm_data or {}
    root = ET.Element(ROOT_TAG, {"lang": _s(pm_data.get("lang")).lower() or "en"})
    ET.SubElement(root, "product-name").text = _s(pm_data.get("product_name"))
    ET.SubElement(root, "din").text = _s(pm_data.get("din"))
    for section in (pm_data.get("sections") or []):
        if not isinstance(section, dict):
            continue
        sec = ET.SubElement(root, "section",
                            {"code": _s(section.get("code") or section.get("heading"))})
        ET.SubElement(sec, "title").text = _s(section.get("title"))
        ET.SubElement(sec, "text").text = _s(section.get("text"))
    for image in (pm_data.get("images") or []):
        href = _s(image.get("href") if isinstance(image, dict) else image)
        if href:
            ET.SubElement(root, "image", {"href": href})
    return ET.tostring(root, encoding="unicode")


def validate_monograph_xml(xml: str) -> dict:
    """Validate an XML PM: well-formed + required elements + CV-checked sections.

    Returns ``{valid, findings}``; ``valid`` is False on any blocking finding.
    """
    findings = []
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError as exc:
        return {"valid": False, "findings": [
            {"rule": "pm_xml_malformed", "severity": "blocking",
             "message": f"XML Product Monograph is not well-formed: {exc}"}]}
    if root.tag != ROOT_TAG:
        findings.append({"rule": "pm_xml_root_invalid", "severity": "blocking",
                         "message": f"root element must be <{ROOT_TAG}>"})
    if not _s(root.findtext("product-name")):
        findings.append({"rule": "pm_product_name_required",
                         "severity": "blocking",
                         "message": "<product-name> is required"})
    if not _s(root.findtext("din")):
        findings.append({"rule": "pm_din_required", "severity": "blocking",
                         "message": "<din> is required"})
    sections = root.findall("section")
    if not sections:
        findings.append({"rule": "pm_sections_required", "severity": "blocking",
                         "message": "at least one <section> is required"})
    for sec in sections:
        code = _s(sec.get("code"))
        if code not in PM_SECTION_CV:
            findings.append({
                "rule": "pm_section_code_uncontrolled", "severity": "warning",
                "code": code,
                "message": f"section code '{code}' is not in the controlled "
                           "vocabulary"})
    blocking = any(f["severity"] == "blocking" for f in findings)
    return {"valid": not blocking, "blocking": blocking, "findings": findings}


def require_xml_pm(ctx: dict) -> dict:
    """Transmit gate (REQ-099): block a PDF-only PM where XML PM is required."""
    ctx = ctx or {}
    blockers = []
    if ctx.get("xml_pm_required") and not ctx.get("has_xml_pm"):
        blockers.append({
            "rule": "xml_pm_required",
            "message": "this activity requires a validated XML Product Monograph "
                       "— a PDF-only PM is not sufficient"})
    return {"can_transmit": not blockers, "blockers": blockers}
