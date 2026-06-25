"""
ANDS Submission Portal — submission-type router + ANDS content model + the
per-section required-document checklist gate.

This ADDITIVE slice implements two previously-unimplemented MUST requirements:

  REQ-004  A submission-type router (NDS/ANDS/SNDS/SANDS/DIN) with decision
           support; when ANDS is selected, configure the ANDS content model so
           Module 4 is not-required, Module 3 (CMC) and Module 5 BE reports are
           required, and the CS-BE (BE-only) path suppresses Modules 2.4-2.7
           (including 2.7.1) while KEEPING the 2.3 QOS required.
  REQ-044  A per-section required-document checklist for the configured ANDS
           content model that PREVENTS a transaction passing the validation gate
           while mandatory documents (incl. the 2.3 QOS-CE, the 1.6 CS-BE copy,
           and required .docx-alongside-PDF) are missing; the cover-letter slot
           is satisfied by the portal-generated sponsor-authored cover letter.

Pure, dependency-free (Python 3 standard library only) and deterministic; the
HTTP layer in server.py is a thin shell over these functions.

Requirement traceability tags (REQ-xxx) reference
specs/ands-submission-portal/requirements.md.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# REQ-004: submission-type router + decision support
# ---------------------------------------------------------------------------

# The HC submission-type router options. ``ands_pathway`` flags the types this
# portal's ANDS content model serves; ``advice`` is the decision-support note.
SUBMISSION_TYPES = {
    "NDS": {
        "label": "New Drug Submission",
        "advice": "Full innovator submission — complete Modules 2-5 "
                  "(safety/efficacy required).",
        "ands_content_model": False,
    },
    "ANDS": {
        "label": "Abbreviated New Drug Submission",
        "advice": "Generic relying on a Canadian Reference Product — "
                  "Module 4 not required; Module 3 (CMC) and Module 5 "
                  "bioequivalence reports required.",
        "ands_content_model": True,
    },
    "SNDS": {
        "label": "Supplement to a New Drug Submission",
        "advice": "Post-NOC change to an NDS — scope the supplement to the "
                  "changed modules.",
        "ands_content_model": False,
    },
    "SANDS": {
        "label": "Supplement to an Abbreviated New Drug Submission",
        "advice": "Post-NOC change to an ANDS — ANDS content rules apply to "
                  "the changed modules.",
        "ands_content_model": True,
    },
    "DIN": {
        "label": "DIN Application",
        "advice": "Drug Identification Number application (no NDS/ANDS "
                  "review pathway).",
        "ands_content_model": False,
    },
}


def is_valid_submission_type(value) -> bool:
    """REQ-004: the value is one of HC's routable submission types."""
    return str(value or "").strip().upper() in SUBMISSION_TYPES


def submission_type_options() -> list:
    """REQ-004: the router options as data (for the UI/API)."""
    return [
        {"code": code, "label": meta["label"], "advice": meta["advice"],
         "ands_content_model": meta["ands_content_model"]}
        for code, meta in SUBMISSION_TYPES.items()
    ]


def route_submission_type(data: dict) -> dict:
    """REQ-004: route a submission type and return decision support.

    ``data`` carries ``submission_type`` and the optional flags
    ``new_indication`` (generic seeking an indication BEYOND the CRP) and
    ``cs_be_only``. Returns the resolved type, its advice, the configured ANDS
    content model when applicable, and any routing advisories.
    """
    data = data or {}
    raw = str(data.get("submission_type", "") or "").strip()
    code = raw.upper()
    if code not in SUBMISSION_TYPES:
        return {
            "valid": False,
            "submission_type": raw,
            "error": (f"'{raw}' is not a recognised submission type "
                      f"(expected one of {', '.join(SUBMISSION_TYPES)})"),
        }

    meta = SUBMISSION_TYPES[code]
    advisories = []
    # REQ-004 AC4: a generic seeking a new indication beyond the CRP is NOT an
    # ANDS candidate — advise the correct pathway.
    if meta["ands_content_model"] and bool(data.get("new_indication")):
        advisories.append({
            "rule": "ands_not_for_new_indication",
            "message": ("A generic seeking a new indication beyond the "
                        "Canadian Reference Product is generally NOT eligible "
                        "for the ANDS pathway — an NDS/SNDS is typically "
                        "required."),
        })

    result = {
        "valid": True,
        "submission_type": code,
        "label": meta["label"],
        "advice": meta["advice"],
        "ands_content_model": meta["ands_content_model"],
        "advisories": advisories,
    }
    if meta["ands_content_model"]:
        result["content_model"] = ands_content_model(
            cs_be_only=bool(data.get("cs_be_only")))
    return result


# ---------------------------------------------------------------------------
# REQ-004: the ANDS content model (module gating)
# ---------------------------------------------------------------------------

# The CTD modules an ANDS content model gates. ``cs_be_suppressed`` marks the
# clinical-summary modules suppressed on the CS-BE (BE-only) path. The note
# captures the ANDS-specific rationale.
_ANDS_MODULES = [
    {"module": "1", "title": "Administrative & regional (Canada)",
     "required": True, "cs_be_suppressed": False,
     "note": "REP/ca-regional, cover letter, CS-BE copy in 1.6 where BE-only."},
    {"module": "2.3", "title": "Quality Overall Summary (QOS-CE)",
     "required": True, "cs_be_suppressed": False,
     "note": "Module 2.3 QOS-CE is required for an ANDS and is NOT suppressed "
             "on the CS-BE path."},
    {"module": "2.4", "title": "Nonclinical Overview",
     "required": False, "cs_be_suppressed": True,
     "note": "Suppressed on the CS-BE (BE-only) path; otherwise as applicable."},
    {"module": "2.5", "title": "Clinical Overview",
     "required": False, "cs_be_suppressed": True,
     "note": "Suppressed on the CS-BE (BE-only) path; otherwise as applicable."},
    {"module": "2.6", "title": "Nonclinical Written & Tabulated Summaries",
     "required": False, "cs_be_suppressed": True,
     "note": "Suppressed on the CS-BE (BE-only) path; otherwise as applicable."},
    {"module": "2.7", "title": "Clinical Summary (incl. 2.7.1)",
     "required": False, "cs_be_suppressed": True,
     "note": "Suppressed on the CS-BE (BE-only) path — emitting 2.7.1 while "
             "suppressing 2.4-2.7 is non-conformant."},
    {"module": "3", "title": "Quality (CMC)",
     "required": True, "cs_be_suppressed": False,
     "note": "Module 3 (CMC) is required for an ANDS."},
    {"module": "4", "title": "Nonclinical Study Reports",
     "required": False, "cs_be_suppressed": False,
     "note": "Module 4 is NOT required for an ANDS (generic relies on the CRP)."},
    {"module": "5", "title": "Clinical Study Reports (BE reports)",
     "required": True, "cs_be_suppressed": False,
     "note": "Module 5 bioequivalence study reports are required for an ANDS."},
]


def ands_content_model(cs_be_only: bool = False) -> dict:
    """REQ-004: the configured ANDS content model (module gating).

    On the CS-BE (BE-only) path the clinical-summary modules 2.4-2.7 (incl.
    2.7.1) are suppressed while 2.3 stays required; on the non-CS-BE-only path
    those modules are completed as applicable. Module 4 is always not-required
    and Modules 3 and 5 are always required for an ANDS.
    """
    cs_be_only = bool(cs_be_only)
    modules = []
    for spec in _ANDS_MODULES:
        suppressed = cs_be_only and spec["cs_be_suppressed"]
        if suppressed:
            required = False
        elif spec["cs_be_suppressed"]:
            # 2.4-2.7 on the non-CS-BE-only path: completed as applicable.
            required = False
        else:
            required = spec["required"]
        modules.append({
            "module": spec["module"],
            "title": spec["title"],
            "required": required,
            "suppressed": suppressed,
            "applicable": not suppressed,
            "note": spec["note"],
        })
    return {
        "submission_type": "ANDS",
        "cs_be_only": cs_be_only,
        "module4_required": False,
        "modules": modules,
    }


# ---------------------------------------------------------------------------
# REQ-044: per-section required-document checklist + gate
# ---------------------------------------------------------------------------

# The mandatory documents per CA Module section for an ANDS content model.
# ``formats`` lists every required format for the slot (a ".docx alongside PDF"
# section lists both). ``cover_letter`` slots are satisfied by the
# portal-generated sponsor-authored cover letter (REQ-044 / REQ-009). The
# ``cs_be_only`` flag on an entry means it is required ONLY on the CS-BE path;
# ``non_cs_be_only`` means required only OFF the CS-BE path.
_REQUIRED_DOCUMENTS = [
    {"section": "1.0", "key": "cover-letter", "title": "Cover letter",
     "formats": ["pdf"], "cover_letter": True},
    {"section": "1.6", "key": "cs-be-copy",
     "title": "CS-BE electronic copy", "formats": ["pdf"],
     "cs_be_only": True},
    {"section": "2.3", "key": "qos-ce",
     "title": "Quality Overall Summary (QOS-CE)",
     "formats": ["pdf", "docx"]},          # .docx alongside the PDF
    {"section": "3.2", "key": "cmc-body",
     "title": "Module 3 Quality (CMC) body", "formats": ["pdf"]},
    {"section": "5.3.1.2", "key": "be-study-report",
     "title": "Comparative bioavailability / BE study report",
     "formats": ["pdf"]},
]


def required_documents(cs_be_only: bool = False) -> list:
    """REQ-044: the required-document checklist for the ANDS content model.

    Returns one entry per mandatory document slot applicable to the configured
    path, each carrying its section, title, required formats, and whether the
    slot is satisfied by the portal-generated cover letter.
    """
    cs_be_only = bool(cs_be_only)
    out = []
    for spec in _REQUIRED_DOCUMENTS:
        if spec.get("cs_be_only") and not cs_be_only:
            continue
        if spec.get("non_cs_be_only") and cs_be_only:
            continue
        out.append({
            "section": spec["section"],
            "key": spec["key"],
            "title": spec["title"],
            "formats": list(spec["formats"]),
            "cover_letter": bool(spec.get("cover_letter")),
        })
    return out


def _present_index(present) -> dict:
    """Normalise the caller's ``present_documents`` into {key: set(formats)}.

    Accepts either a list of ``{"key","formats"}`` / ``{"section","formats"}``
    entries or a mapping of key -> list-of-formats. Missing format lists default
    to ["pdf"].
    """
    index: dict = {}
    if isinstance(present, dict):
        items = [{"key": k, "formats": v} for k, v in present.items()]
    else:
        items = list(present or [])
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("section") or "").strip()
        if not key:
            continue
        fmts = item.get("formats")
        if isinstance(fmts, str):
            fmts = [fmts]
        elif fmts is None:
            fmts = ["pdf"]
        index.setdefault(key, set()).update(
            str(f).strip().lower() for f in fmts if str(f).strip())
    return index


def checklist_gate(data: dict) -> dict:
    """REQ-044: block the validation gate while mandatory documents are missing.

    ``data`` carries ``cs_be_only`` and ``present_documents`` (the documents the
    author has supplied). The cover-letter slot is satisfied automatically by
    the portal-generated sponsor-authored cover letter unless the caller
    explicitly sets ``cover_letter_generated`` False. Returns
    ``{"can_pass", "cs_be_only", "missing", "satisfied"}`` where each ``missing``
    finding is mapped to its section and names the missing format(s).
    """
    data = data or {}
    cs_be_only = bool(data.get("cs_be_only"))
    cover_generated = data.get("cover_letter_generated", True)
    present = _present_index(data.get("present_documents"))

    missing = []
    satisfied = []
    for spec in required_documents(cs_be_only):
        key = spec["key"]
        need = [f.lower() for f in spec["formats"]]
        # The cover-letter slot is satisfied by the portal-generated document.
        if spec["cover_letter"] and cover_generated:
            satisfied.append({"section": spec["section"], "key": key,
                              "title": spec["title"],
                              "source": "portal-generated"})
            continue
        have = present.get(key, set())
        missing_formats = [f for f in need if f not in have]
        if not have:
            missing.append({
                "rule": "missing_required_document",
                "section": spec["section"], "key": key, "title": spec["title"],
                "missing_formats": need,
                "message": (f"Section {spec['section']} requires "
                            f"'{spec['title']}' ({'/'.join(need)}) — none "
                            "supplied"),
            })
        elif missing_formats:
            missing.append({
                "rule": "missing_required_format",
                "section": spec["section"], "key": key, "title": spec["title"],
                "missing_formats": missing_formats,
                "message": (f"Section {spec['section']} '{spec['title']}' "
                            f"requires the {'/'.join(missing_formats)} "
                            "format alongside the PDF"),
            })
        else:
            satisfied.append({"section": spec["section"], "key": key,
                              "title": spec["title"], "source": "supplied"})

    return {
        "can_pass": not missing,
        "cs_be_only": cs_be_only,
        "missing": missing,
        "satisfied": satisfied,
    }
