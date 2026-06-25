"""
ANDS Submission Portal — Study Tagging File (STF) generation & validation.

This ADDITIVE slice implements REQ-064: a DEDICATED STF capability, validated as
its own HC eCTD validation category (distinct from General/PDF/Referenced/etc.).

  REQ-064  Provide a dedicated Study Tagging File (STF) generation and validation
           capability for transactions containing study data, generating
           conformant STF leaves where Module 5 BE study reports (or any
           Module 4/5 study data) appear, and validating them as their own HC
           eCTD validation category.

The existing ``validation._check_stf`` (S01) flags a study that REQUIRES an STF
but has none. This module is the BUILDER + the category-level validator: it
generates conformant STF leaves and validates each STF against the STF rules,
independent of the other categories. Pure, dependency-free (stdlib only) and
deterministic.
"""

from __future__ import annotations

from xml.dom.minidom import parseString
from xml.sax.saxutils import escape as _xml_escape


STF_CATEGORY = "STF"
# Module 4/5 study data is where STFs apply. ANDS BE reports live in 5.3.1.2.
STF_MODULES = ("4", "5")
STF_DTD_VERSION = "2-2"          # ICH STF DTD (HC-published, stand-in)
STF_FILE_TAGS = ("study-report-body", "synopsis", "annex")


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def _requires_stf(study: dict) -> bool:
    """A Module 4/5 study report requires an STF unless explicitly opted out."""
    return bool((study or {}).get("requires_stf", True))


def stf_leaf_id(study: dict) -> str:
    sid = _norm((study or {}).get("id") or (study or {}).get("type") or "study")
    return f"stf-{sid}"


def build_stf_leaf(study: dict) -> dict:
    """REQ-064: generate one conformant STF leaf for a Module 4/5 study.

    Returns a leaf descriptor ``{leaf_id, href, category, xml, study_id, ...}``.
    The STF XML carries the study identification + tagged file leaves HC's STF
    category expects.
    """
    study = study or {}
    sid = _norm(study.get("id") or study.get("type") or "study")
    folder = _norm(study.get("folder")) or "m5/53-clin-stud-rep/531-bio/5312-comp-ba-be"
    title = _norm(study.get("title")) or f"Bioequivalence study {sid}"
    study_type = _norm(study.get("type")) or "bioequivalence"
    files = study.get("files") or ["study-report-body"]

    file_xml = "".join(
        f'    <file-tag name="{_xml_escape(_norm(f))}" '
        f'xlink:href="{_xml_escape(folder)}/{_xml_escape(_norm(f))}.pdf"/>\n'
        for f in files
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<ectd-stf dtd-version="{STF_DTD_VERSION}" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        f"  <study-id>{_xml_escape(sid)}</study-id>\n"
        f"  <study-title>{_xml_escape(title)}</study-title>\n"
        f"  <study-category>{_xml_escape(study_type)}</study-category>\n"
        "  <file-tags>\n"
        f"{file_xml}"
        "  </file-tags>\n"
        "</ectd-stf>\n"
    )
    return {
        "leaf_id": stf_leaf_id(study),
        "study_id": sid,
        "href": f"{folder}/stf-{sid}.xml",
        "category": STF_CATEGORY,
        "folder": folder,
        "xml": xml,
    }


def generate_stfs(module5_studies) -> list:
    """REQ-064: generate STF leaves for every study that requires one."""
    out = []
    for study in (module5_studies or []):
        if _requires_stf(study):
            out.append(build_stf_leaf(study))
    return out


def validate_stf(stf: dict) -> list:
    """REQ-064: validate ONE STF against the STF category rules.

    Checks well-formedness and the required STF elements (study-id, study-title,
    study-category, at least one file-tag). Returns ``{"rule","message","category"}``
    findings (empty == conformant). All findings carry ``category == "STF"`` so
    they are reported independently of the other validation categories.
    """
    out = []

    def add(rule, message):
        out.append({"rule": rule, "message": message, "category": STF_CATEGORY})

    xml = _norm((stf or {}).get("xml"))
    if not xml:
        add("stf_missing_xml", "STF has no XML body")
        return out
    try:
        dom = parseString(xml)
    except Exception as exc:
        add("stf_malformed", f"STF is not well-formed XML: {exc}")
        return out

    if dom.documentElement.tagName != "ectd-stf":
        add("stf_wrong_root",
            f"STF root element '{dom.documentElement.tagName}' is not 'ectd-stf'")

    for tag in ("study-id", "study-title", "study-category"):
        nodes = dom.getElementsByTagName(tag)
        text = ""
        if nodes:
            text = "".join(t.data for t in nodes[0].childNodes
                           if t.nodeType == t.TEXT_NODE).strip()
        if not text:
            add("stf_missing_element",
                f"STF required element <{tag}> is missing or empty")

    if not dom.getElementsByTagName("file-tag"):
        add("stf_no_file_tags",
            "STF has no <file-tag> leaves — at least one tagged study file is "
            "required")
    return out


def validate_stf_category(module5_studies) -> dict:
    """REQ-064: validate the STF category across a transaction's study data.

    For each Module 4/5 study that requires an STF: if the study carries no STF
    (neither a present flag nor an attached ``stf`` body) it is a blocking
    STF-category defect; if it carries an STF body, the STF is validated against
    the category rules. Returns
    ``{"category", "valid", "blocking", "findings", "generated"}``.

    ``generated`` is the set of STF leaves the builder would emit for studies
    that lack one — so the UI can offer to add them.
    """
    findings = []
    generated = []
    for study in (module5_studies or []):
        if not _requires_stf(study):
            continue
        sid = _norm(study.get("id") or study.get("type") or "study")
        stf_body = study.get("stf")
        present = bool(study.get("stf_present")) or bool(stf_body)
        if not present:
            findings.append({
                "rule": "stf_required_missing",
                "category": STF_CATEGORY,
                "study": sid,
                "message": (f"Module 5 study '{sid}' contains study data but has "
                            "no Study Tagging File (STF)"),
            })
            generated.append(build_stf_leaf(study))
            continue
        if stf_body:
            for f in validate_stf(stf_body):
                f = dict(f)
                f["study"] = sid
                findings.append(f)
        elif not study.get("stf_valid", True):
            findings.append({
                "rule": "stf_invalid",
                "category": STF_CATEGORY,
                "study": sid,
                "message": (f"the Study Tagging File for study '{sid}' is "
                            "present but malformed/incorrect"),
            })
    return {
        "category": STF_CATEGORY,
        "valid": not findings,
        "blocking": bool(findings),
        "findings": findings,
        "generated": generated,
    }
