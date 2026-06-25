"""
ANDS Submission Portal — Quality Overall Summary, Chemical Entities (QOS-CE).

This ADDITIVE slice implements REQ-061: the Health Canada QOS-CE template for
Module 2.3, parallel to the CS-BE handling in REQ-008.

  REQ-061  Generate, fill and validate the HC Quality Overall Summary — Chemical
           Entities (QOS-CE) template for Module 2.3, and FLAG a missing or
           incomplete QOS-CE as a screening-deficiency risk.

The QOS-CE is mandatory for an ANDS (Module 3 + the 2.3 QOS-CE); a missing or
structurally-incomplete QOS is a screening-deficiency risk. Pure, dependency-free
(Python 3 standard library only) and deterministic.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _xml_escape


QOS_CE_MODULE = "2.3"
QOS_CE_LEAF = "m2-3-qos-ce"


# The structural sections of the HC QOS-CE (Chemical Entities) template. Each
# section must be present and non-empty for the QOS to be structurally complete.
# Mirrors the HC QOS-CE layout: Introduction, 2.3.S Drug Substance, 2.3.P Drug
# Product, 2.3.A Appendices, 2.3.R Regional Information.
QOS_CE_SECTIONS = [
    {"key": "introduction", "code": "2.3.I", "title": "Introduction"},
    {"key": "drug_substance", "code": "2.3.S", "title": "Drug Substance"},
    {"key": "drug_product", "code": "2.3.P", "title": "Drug Product"},
    {"key": "appendices", "code": "2.3.A", "title": "Appendices"},
    {"key": "regional", "code": "2.3.R", "title": "Regional Information"},
]


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def qos_ce_template() -> dict:
    """REQ-061: the QOS-CE template structure as data (for the builder UI/API)."""
    return {
        "module": QOS_CE_MODULE,
        "leaf_id": QOS_CE_LEAF,
        "title": "Quality Overall Summary — Chemical Entities (QOS-CE)",
        "sections": [dict(s) for s in QOS_CE_SECTIONS],
    }


def validate_qos_ce(data: dict) -> list:
    """REQ-061: structural-completeness check against the HC QOS-CE template.

    ``data`` carries a ``sections`` map (section key -> filled content). Returns
    ``{"rule","message","section","code"}`` findings — one per missing/empty
    required section (empty == structurally complete). A wholly absent QOS-CE
    yields a finding for every required section.
    """
    out = []
    sections = (data or {}).get("sections") or {}
    for sec in QOS_CE_SECTIONS:
        if not _norm(sections.get(sec["key"])):
            out.append({
                "rule": "qos_ce_section_incomplete",
                "section": sec["key"],
                "code": sec["code"],
                "message": (f"QOS-CE section {sec['code']} "
                            f"({sec['title']}) is missing or empty"),
            })
    return out


def build_qos_ce(data: dict) -> dict:
    """REQ-061: generate + fill a conformant QOS-CE document for Module 2.3.

    Returns ``{"valid", "errors", "qos_ce"}``. ``valid`` is False when the
    QOS-CE is structurally incomplete; ``qos_ce`` is still produced (with the
    filled sections) so the author can see what is missing.
    """
    data = data or {}
    sections = data.get("sections") or {}
    errors = validate_qos_ce(data)
    qos_ce = {
        "module": QOS_CE_MODULE,
        "leaf_id": QOS_CE_LEAF,
        "title": "Quality Overall Summary — Chemical Entities (QOS-CE)",
        "drug_product": _norm(data.get("drug_product")),
        "sections": [
            {"key": s["key"], "code": s["code"], "title": s["title"],
             "content": _norm(sections.get(s["key"])),
             "complete": bool(_norm(sections.get(s["key"]))),
             "module": QOS_CE_MODULE}
            for s in QOS_CE_SECTIONS
        ],
        "complete": not errors,
        "document": _render_qos_ce_xml(data),
    }
    return {"valid": not errors, "errors": errors, "qos_ce": qos_ce}


def _render_qos_ce_xml(data: dict) -> str:
    """A conformant QOS-CE document body (deterministic)."""
    data = data or {}
    sections = data.get("sections") or {}
    body = "".join(
        f'  <section code="{_xml_escape(s["code"])}" '
        f'key="{_xml_escape(s["key"])}">'
        f'{_xml_escape(_norm(sections.get(s["key"])))}'
        '</section>\n'
        for s in QOS_CE_SECTIONS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<qos-ce module="{QOS_CE_MODULE}">\n'
        f'  <product>{_xml_escape(_norm(data.get("drug_product")))}</product>\n'
        f"{body}"
        '</qos-ce>\n'
    )


def qos_ce_gate(data: dict) -> dict:
    """REQ-061: the screening-deficiency-risk gate for the QOS-CE.

    A missing or incomplete QOS-CE BLOCKS with a screening-deficiency-risk
    finding mapped to Module 2.3. Returns
    ``{"can_pass", "screening_deficiency_risk", "module", "findings"}``.
    """
    findings = validate_qos_ce(data)
    present = bool((data or {}).get("sections"))
    gate = {
        "module": QOS_CE_MODULE,
        "can_pass": not findings,
        "screening_deficiency_risk": bool(findings),
        "present": present,
        "findings": findings,
    }
    if findings:
        reason = ("QOS-CE is absent" if not present
                  else "QOS-CE is structurally incomplete")
        gate["risk_message"] = (
            f"{reason} — a missing/incomplete Module 2.3 QOS-CE is a "
            "screening-deficiency risk")
    return gate
