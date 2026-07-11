"""XML Product Monograph builder/validator (REQ-099) — pure, stdlib only.

Generates a structured XML Product Monograph (ElementTree auto-escapes content)
and validates it: well-formedness + required elements + section codes against a
controlled vocabulary. A transmit gate blocks a PDF-only PM where XML is required.
No lxml — XSD/CV are embedded as data.

Hardened with a stylesheet-package machinery (REQ-065/REQ-040) applied to
the XML PM view:

  * HC's XML PM stylesheet package (SPL Canada stylesheet,
    ``spl_canada`` version ``v_1_0``) is held as VERSIONED REFERENCE
    DATA — a registry keyed by package version; a newer HC edition is
    registered as data, never a code change (REQ-040). The stylesheet
    RENDERS the HC view; validation is against the SPL schema /
    validation rules / controlled vocabulary.
  * The PM "view" is expressed as DATA (field rules) and drives the
    structure/style checks: version-matched stylesheet selection, blank-value
    style findings (blanks render as "—" in the HC view), duplicate section
    codes, image href presence and the EN/FR language set.
  * Caller-supplied XML passes the monolith's ``xmlsafe`` entity hardening
    (billion-laughs / XXE) before any parse.
"""

from __future__ import annotations

import copy
import datetime as _dt
import xml.etree.ElementTree as ET
from xml.parsers.expat import ParserCreate

ROOT_TAG = "product-monograph"

# controlled vocabulary of PM section codes (a representative HC XML-PM subset)
PM_SECTION_CV = ("indications", "contraindications", "warnings", "dosage",
                 "adverse-reactions", "pharmacology", "storage", "supply",
                 "patient-information")


def _s(v) -> str:
    return str(v if v is not None else "").strip()


# ---------------------------------------------------------------------------
# Stylesheet package registry (rep_stylesheet.py port — REQ-065/REQ-040)
# ---------------------------------------------------------------------------

# HC's published XML PM stylesheet package identity: the SPL Canada
# stylesheet, style-sheet/v_1_0/ in the HPFB XML-PM repo
# (https://github.com/hpfb-dgpsa/XML-PM). The stylesheet renders the EN/FR
# view; validation is against the SPL schema / validation rules / CV.
STYLESHEET_PACKAGE = "spl_canada"
BUNDLED_STYLESHEET_VERSION = "v_1_0"

# The PM view as DATA: an ordered list of field rules a generic checker
# interprets. Adding/renaming a rule is a DATA edit — no checker change.
_PM_VIEW_V_1_0 = {
    "package": STYLESHEET_PACKAGE,
    "version": BUNDLED_STYLESHEET_VERSION,
    "title": "Health Canada XML PM stylesheet view",
    "root_tag": ROOT_TAG,
    "version_attr": "stylesheet-version",
    "langs": ("en", "fr"),           # HC PM editions are English/French
    "fields": [
        {"path": "product-name", "label": "Product name",
         "rule": "pm_product_name_required"},
        {"path": "din", "label": "DIN", "rule": "pm_din_required"},
    ],
    "section_fields": ("title", "text"),
}

# The version registry. Keyed by package version. A newer HC
# package is added with ``register_stylesheet_package`` — no call site changes.
_STYLESHEET_PACKAGES = {
    BUNDLED_STYLESHEET_VERSION: _PM_VIEW_V_1_0,
}


class StylesheetVersionError(KeyError):
    """Raised when no bundled stylesheet matches the requested version."""


class UnsafeXmlError(ValueError):
    """Raised when XML carries a DTD entity declaration or external entity
    reference — the building blocks of billion-laughs / XXE attacks."""


def available_stylesheet_versions() -> list:
    """Every bundled stylesheet package version, newest version last."""
    return sorted(_STYLESHEET_PACKAGES)


def active_stylesheet_version() -> str:
    """The most recent bundled package version (latest in sort order)."""
    return available_stylesheet_versions()[-1]


def load_stylesheet(version: str = "") -> dict:
    """Load a bundled stylesheet package edition by version (active default).

    Returns a deep copy so callers can never mutate the canonical store.
    """
    ver = _s(version) or active_stylesheet_version()
    pkg = _STYLESHEET_PACKAGES.get(ver)
    if pkg is None:
        raise StylesheetVersionError(
            f"no XML PM stylesheet bundled for version {ver!r} "
            f"(have: {', '.join(available_stylesheet_versions())})")
    return copy.deepcopy(pkg)


def register_stylesheet_package(version: str, package: dict) -> None:
    """REQ-040: load a newer HC stylesheet package AS DATA (no code change)."""
    ver = _s(version)
    if not ver:
        raise ValueError("a stylesheet package version is required")
    if not isinstance(package, dict) or "fields" not in package:
        raise ValueError("a stylesheet package must be a dict carrying "
                         "'fields'")
    _STYLESHEET_PACKAGES[ver] = package


def _assert_entity_safe(xml_text) -> None:
    """Reject entity-expansion (billion laughs) and external-entity (XXE) XML.

    Ported from the monolith's ``xmlsafe.assert_xml_entity_safe`` — the same
    hardening ``rep_stylesheet`` runs before rendering caller-supplied XML.
    Fires on the *declaration* of any entity, before it could ever expand;
    lets a merely malformed document fall through to the caller's own
    well-formedness handling.
    """
    parser = ParserCreate()
    # Never parse external parameter entities (closes the XXE vector).
    parser.SetParamEntityParsing(0)  # XML_PARAM_ENTITY_PARSING_NEVER

    def _reject(*_args):
        raise UnsafeXmlError("XML entity declarations / external entities "
                             "are not permitted in a Product Monograph")

    parser.EntityDeclHandler = _reject
    parser.ExternalEntityRefHandler = _reject
    data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    try:
        parser.Parse(data, True)
    except UnsafeXmlError:
        raise
    except Exception:
        return


# ---------------------------------------------------------------------------
# Build / validate
# ---------------------------------------------------------------------------

def build_monograph_xml(pm_data: dict) -> str:
    """Build an XML Product Monograph from structured data (auto-escaped).

    Stamps the active stylesheet package version on the root — mirroring how
    REP templates stamp ``template-version`` so the stylesheet edition used
    for review is version-matched to the artifact (REQ-065).
    """
    pm_data = pm_data or {}
    root = ET.Element(ROOT_TAG, {
        "lang": _s(pm_data.get("lang")).lower() or "en",
        "stylesheet-version": active_stylesheet_version(),
    })
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
    Structure/style checks beyond the originals are the rep_stylesheet.py
    port: entity-safety, version-matched stylesheet selection, blank-field
    and duplicate-code style findings, image href presence, EN/FR language.
    """
    findings = []
    try:
        _assert_entity_safe(xml or "")
    except UnsafeXmlError as exc:
        return {"valid": False, "blocking": True, "findings": [
            {"rule": "pm_xml_entity_unsafe", "severity": "blocking",
             "message": str(exc)}]}
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError as exc:
        return {"valid": False, "blocking": True, "findings": [
            {"rule": "pm_xml_malformed", "severity": "blocking",
             "message": f"XML Product Monograph is not well-formed: {exc}"}]}
    view = _STYLESHEET_PACKAGES[active_stylesheet_version()]
    if root.tag != view.get("root_tag", ROOT_TAG):
        findings.append({"rule": "pm_xml_root_invalid", "severity": "blocking",
                         "message": f"root element must be <{ROOT_TAG}>"})
    # version matching (rep_stylesheet.stylesheet_for_template): a document
    # that names a stylesheet edition must name a BUNDLED one; a document
    # with no version attribute falls back to the active edition.
    doc_version = _s(root.get(view.get("version_attr", "")))
    if doc_version and doc_version not in _STYLESHEET_PACKAGES:
        findings.append({
            "rule": "pm_stylesheet_version_unmatched", "severity": "blocking",
            "version": doc_version,
            "message": f"no bundled XML PM stylesheet matches version "
                       f"{doc_version!r} (have: "
                       f"{', '.join(available_stylesheet_versions())})"})
    lang = _s(root.get("lang")).lower()
    if lang and lang not in view.get("langs", ("en", "fr")):
        findings.append({
            "rule": "pm_lang_uncontrolled", "severity": "warning",
            "lang": lang,
            "message": f"language '{lang}' has no EN/FR stylesheet edition"})
    for rule in view.get("fields", []):
        if not _s(root.findtext(rule["path"])):
            findings.append({"rule": rule["rule"], "severity": "blocking",
                             "message": f"<{rule['path']}> is required"})
    sections = root.findall("section")
    if not sections:
        findings.append({"rule": "pm_sections_required", "severity": "blocking",
                         "message": "at least one <section> is required"})
    seen_codes = set()
    for sec in sections:
        code = _s(sec.get("code"))
        if code not in PM_SECTION_CV:
            findings.append({
                "rule": "pm_section_code_uncontrolled", "severity": "warning",
                "code": code,
                "message": f"section code '{code}' is not in the controlled "
                           "vocabulary"})
        if code and code in seen_codes:
            findings.append({
                "rule": "pm_section_code_duplicate", "severity": "warning",
                "code": code,
                "message": f"section code '{code}' appears more than once"})
        seen_codes.add(code)
        # style: a blank value renders as the "—" placeholder in the HC view
        for field in view.get("section_fields", ()):
            if not _s(sec.findtext(field)):
                findings.append({
                    "rule": "pm_section_blank_field", "severity": "warning",
                    "code": code, "field": field,
                    "message": f"section '{code}' has a blank <{field}> "
                               "(renders as '—' in the HC view)"})
    for image in root.findall("image"):
        if not _s(image.get("href")):
            findings.append({
                "rule": "pm_image_href_required", "severity": "blocking",
                "message": "<image> must carry a non-empty href (REQ-099 "
                           "related image assets)"})
    blocking = any(f["severity"] == "blocking" for f in findings)
    return {"valid": not blocking, "blocking": blocking, "findings": findings}


# ---------------------------------------------------------------------------
# Transmit gate (REQ-099) + the HC generic mandate-wave trigger
# ---------------------------------------------------------------------------

# HC phases the XML PM mandate in by filer class — innovators (new brand
# submissions) first, generics (ANDS) in the ~2026-2027 wave.
# Source: this project's HC research — docs/ands-portal/
# COMPETITIVE-REQUIREMENTS-INVENTORY.md COMP-CA-002 (XML PM rules, "HC
# 2024+") and VISION-GAP-REQUIREMENTS.md REQ-099 / the Phase-4 "full XML PM"
# scope decision. Neither the monolith's rep_stylesheet.py nor its
# content_model.py fixes a binding HC date, so — following the monolith's
# backbone.py ADOPTION_ROADMAP convention — the wave dates below are
# conservative start-of-window ESTIMATES, flagged ``estimate``/``hc_fixed``
# so no UI may present them as HC-fixed commitments. They are reference
# DATA (REQ-040): update the tuple when HC publishes the binding notice.
XML_PM_MANDATE_WAVES = (
    {"wave": "innovator", "pathways": ("innovator", "nds", "brand"),
     "effective": "2025-01-01", "estimate": True, "hc_fixed": False},
    {"wave": "generic", "pathways": ("generic", "ands", "abbreviated"),
     "effective": "2026-01-01", "estimate": True, "hc_fixed": False},
)


def xml_pm_mandate_wave(pathway) -> dict | None:
    """The mandate wave covering ``pathway``, or None when none does."""
    p = _s(pathway).lower()
    for wave in XML_PM_MANDATE_WAVES:
        if p in wave["pathways"]:
            return dict(wave)
    return None


def _parse_date(value):
    try:
        return _dt.date.fromisoformat(_s(value)[:10])
    except ValueError:
        return None


def xml_pm_required_by_mandate(pathway, filing_date) -> bool:
    """True when a filing is caught by its class's XML PM mandate wave.

    Lenient by design: an unknown pathway or an unparseable filing date
    never triggers the mandate (the explicit ``xml_pm_required`` flag stays
    the way to force the gate).
    """
    wave = xml_pm_mandate_wave(pathway)
    filed = _parse_date(filing_date)
    if wave is None or filed is None:
        return False
    return filed >= _dt.date.fromisoformat(wave["effective"])


def require_xml_pm(ctx: dict) -> dict:
    """Transmit gate (REQ-099): block a PDF-only PM where XML PM is required.

    The explicit ``xml_pm_required`` flag keeps its original behaviour for
    existing callers. When the flag is not set, the requirement is derived
    from the HC mandate waves: a generic (or innovator) filing dated on/after
    its wave's effective date requires a validated XML PM.
    """
    ctx = ctx or {}
    blockers = []
    pathway = (ctx.get("pathway") or ctx.get("submission_pathway")
               or ctx.get("submission_type"))
    filing_date = ctx.get("filing_date") or ctx.get("planned_filing_date")
    if not ctx.get("has_xml_pm"):
        if ctx.get("xml_pm_required"):
            blockers.append({
                "rule": "xml_pm_required",
                "message": "this activity requires a validated XML Product "
                           "Monograph — a PDF-only PM is not sufficient"})
        elif xml_pm_required_by_mandate(pathway, filing_date):
            wave = xml_pm_mandate_wave(pathway)
            blockers.append({
                "rule": "xml_pm_mandate_wave",
                "wave": wave["wave"],
                "effective": wave["effective"],
                "estimate": wave["estimate"],
                "hc_fixed": wave["hc_fixed"],
                "message": f"a {wave['wave']} filing dated on/after "
                           f"{wave['effective']} falls in the HC XML PM "
                           "mandate wave (estimated effective date) — a "
                           "PDF-only PM is not sufficient"})
    return {"can_transmit": not blockers, "blockers": blockers}
