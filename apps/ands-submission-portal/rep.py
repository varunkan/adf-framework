"""
ANDS Submission Portal — REP (Regulatory Enrolment Process) domain logic.

This module is the ADDITIVE slice covering REP CO/RT/PI template generation,
HC identifier-format validation, the HC Module-1 regulatory-activity controlled
vocabulary, and single-entry metadata flow into the eCTD ca-regional.xml
backbone and the sponsor-authored cover letter.

Pure, dependency-free (Python 3 standard library only) and deterministic: every
function that stamps a filename accepts an explicit ``now`` so output is
reproducible and unit-testable. The HTTP/API/UI layer in server.py is a thin
shell over these functions.

Requirement traceability (specs/ands-submission-portal/{requirements,spec}.md):
  REQ-001  REP CO template form + immutable machine-generated filename
  REQ-005  Regulatory-activity controlled vocabulary -> RT template (I08)
  REQ-006  RT (v5.1.0) + PI (2024-02-12) templates; metadata in m1/ca/ca-regional.xml;
           AI template / 1.04-1.05 placement are device-only (NOT used for drug ANDS)
  REQ-042  Identifier formats: Company ID opaque token, Dossier ID prefix-by-type,
           sequence 4-digit, DIN 8-digit
  REQ-043  Single-entry REP CO/RT/PI identifiers flow into ca-regional.xml +
           auto-populate the portal's own cover-letter template
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape


# ---------------------------------------------------------------------------
# Pinned REP / reference-data versions (REQ-006 / REQ-040)
# ---------------------------------------------------------------------------

CO_TEMPLATE_VERSION = "5.0.0"          # REP Company template
RT_TEMPLATE_VERSION = "5.1.0"          # REP Regulatory Transaction template
RT_TEMPLATE_DATE = "2025-09-10"
PI_TEMPLATE_VERSION = "2024-02-12"     # REP Product Information template
CA_MODULE1_SCHEMA_VERSION = "2.2"      # CA Module 1 Schema (XSD 2012-07-06)

# Where a DRUG ANDS REP transaction's metadata belongs. The Application
# Information (AI) template and the 1.04/1.05 folder placement are
# MEDICAL-DEVICE / IMDRF-only and are deliberately NOT produced on this path.
CA_REGIONAL_PATH = "m1/ca/ca-regional.xml"
COVER_LETTER_LEAF = "m1-0-1-cover-letter"   # heading 1.0, sponsor-authored


# ---------------------------------------------------------------------------
# Identifier formats (REQ-042)
# ---------------------------------------------------------------------------

# Company ID is an HC-ASSIGNED OPAQUE TOKEN. The only published sample
# (final-com-K18276-...) is 6-char alphanumeric, so this is validated LOOSELY:
# alphanumeric, a sane length band (2-12 chars) — and explicitly NOT hardcoded
# to 5 digits. A bare single character is rejected as too short to be a token.
COMPANY_ID_RE = re.compile(r"[A-Za-z0-9]{2,12}")

# Drug Dossier ID is prefix-by-type: a single lowercase letter then 6 or 7
# digits. Default ANDS prefix is 'e' (pharma/biologic & eCTD Master Files);
# 'f' = non-eCTD Master Files, 'm' = medical device.
DOSSIER_TYPE_PREFIXES = {
    "e": "Pharmaceutical / biologic eCTD (& eCTD Master Files)",
    "f": "Non-eCTD Master Files",
    "m": "Medical device",
}

# Drug Identification Number: exactly 8 digits.
DIN_RE = re.compile(r"[0-9]{8}")

# Sequence folder: exactly four digits (mirrors domain.SEQUENCE_RE).
SEQUENCE_RE = re.compile(r"[0-9]{4}")


def is_valid_company_id(value: str) -> bool:
    """REQ-042: Company ID is an opaque alphanumeric HC token (loose).

    Accepts e.g. ``K18276`` *and* plain digits; rejects empty, whitespace, and
    anything with separators/punctuation. Deliberately NOT a 5-digit rule.
    """
    return bool(COMPANY_ID_RE.fullmatch(str(value or "").strip()))


def is_valid_dossier_id(value: str, prefix: str = "e") -> bool:
    """REQ-042: prefix-by-type Dossier ID — ``<prefix>`` + 6 or 7 digits.

    ``prefix`` defaults to the ANDS 'e' convention; pass 'm'/'f' for the other
    branches. A multi-character or unknown prefix is rejected.
    """
    prefix = str(prefix or "e")
    if len(prefix) != 1 or not prefix.isalpha():
        return False
    pattern = re.compile(prefix + r"[0-9]{6,7}")
    return bool(pattern.fullmatch(str(value or "").strip()))


def is_valid_sequence(value: str) -> bool:
    """REQ-042: sequence folder — exactly four digits."""
    return bool(SEQUENCE_RE.fullmatch(str(value or "").strip()))


def is_valid_din(value: str) -> bool:
    """REQ-042: DIN — exactly 8 digits."""
    return bool(DIN_RE.fullmatch(str(value or "").strip()))


def validate_identifiers(data: dict) -> list:
    """Validate every identifier present in ``data`` at input (REQ-042).

    Only validates fields that are present and non-empty (so the same helper
    serves partial forms); returns one ``{"rule","message"}`` per failure.
    DIN is optional and only checked when supplied.
    """
    errors: list = []

    def add(rule: str, message: str):
        errors.append({"rule": rule, "message": message})

    company_id = str(data.get("company_id", "") or "").strip()
    dossier_id = str(data.get("dossier_id", "") or "").strip()
    prefix = str(data.get("dossier_prefix", "e") or "e").strip() or "e"
    sequence = str(data.get("sequence", "") or "").strip()
    din = str(data.get("din", "") or "").strip()

    if company_id and not is_valid_company_id(company_id):
        add("company_id_format",
            "Company ID must be an HC-assigned alphanumeric token "
            "(3-12 letters/digits, e.g. K18276) — it is NOT a 5-digit number")
    if dossier_id and not is_valid_dossier_id(dossier_id, prefix):
        add("dossier_id_format",
            f"Dossier ID must be '{prefix}' followed by 6 or 7 digits "
            f"(e.g. {prefix}123456)")
    if sequence and not is_valid_sequence(sequence):
        add("sequence_format",
            "Sequence number must be exactly 4 digits (0000-9999)")
    if din and not is_valid_din(din):
        add("din_format", "DIN must be exactly 8 digits")

    return errors


# ---------------------------------------------------------------------------
# Regulatory-activity controlled vocabulary (REQ-005)
# ---------------------------------------------------------------------------

# HC Module-1 regulatory-activity-type controlled vocabulary (keyed to the
# Module 1 schema version). Out-of-vocabulary values are rejected, mirroring
# eCTD validation rule I08. ANDS is present, as required.
ACTIVITY_TYPES = {
    "NDS": "New Drug Submission (NDS)",
    "ANDS": "Abbreviated New Drug Submission (ANDS)",
    "SNDS": "Supplement to a New Drug Submission (SNDS)",
    "SANDS": "Supplement to an Abbreviated New Drug Submission (SANDS)",
    "DINA": "Drug Identification Number Application (DINA)",
    "NC": "Notifiable Change (NC)",
    "CTA": "Clinical Trial Application (CTA)",
}


def is_valid_activity_type(value: str) -> bool:
    """REQ-005: the activity-type code must be in HC's controlled vocabulary."""
    return str(value or "").strip() in ACTIVITY_TYPES


def activity_type_label(value: str) -> str:
    """Human-readable label for a CV code; '' for an unknown code."""
    return ACTIVITY_TYPES.get(str(value or "").strip(), "")


# ---------------------------------------------------------------------------
# Machine-generated, immutable REP filenames (REQ-001 / REQ-006)
# ---------------------------------------------------------------------------

def _stamp(now: datetime | None) -> tuple:
    """Return (YYYY-MM-DD, HHMM) for a filename stamp (UTC default)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.strftime("%H%M")


def co_filename(company_id: str, now: datetime | None = None) -> str:
    """REQ-001: ``final-com-<COMPANYID>-<YYYY-MM-DD>-<HHMM>.xml`` (immutable)."""
    day, hhmm = _stamp(now)
    return f"final-com-{str(company_id).strip()}-{day}-{hhmm}.xml"


def rt_filename(dossier_id: str, now: datetime | None = None) -> str:
    """REQ-006: machine-generated immutable RT filename."""
    day, hhmm = _stamp(now)
    return f"final-rt-{str(dossier_id).strip()}-{day}-{hhmm}.xml"


def pi_filename(dossier_id: str, now: datetime | None = None) -> str:
    """REQ-006: machine-generated immutable PI filename."""
    day, hhmm = _stamp(now)
    return f"final-pi-{str(dossier_id).strip()}-{day}-{hhmm}.xml"


class ImmutableFilenameError(ValueError):
    """Raised when a user tries to rename a machine-generated REP file."""


def assert_rep_filename_immutable(original: str, proposed: str) -> None:
    """REQ-001: REP filenames are machine-generated and immutable.

    Any attempt to rename or change the extension is blocked.
    """
    if str(proposed).strip() != str(original).strip():
        raise ImmutableFilenameError(
            f"REP filenames are immutable: '{original}' may not be renamed to "
            f"'{proposed}'")


# ---------------------------------------------------------------------------
# REP / backbone XML + cover-letter generation
# ---------------------------------------------------------------------------

def _e(value) -> str:
    return _xml_escape(str(value if value is not None else "").strip())


def build_co_xml(data: dict) -> str:
    """REQ-001: conformant REP CO (Company) XML.

    Captures sponsor details and the contact (with its HC-issued contact ID)
    for reference by later transactions.
    """
    contacts = data.get("contacts") or []
    contact_xml = ""
    for c in contacts:
        contact_xml += (
            "  <contact>\n"
            f"    <name>{_e(c.get('name'))}</name>\n"
            f"    <email>{_e(c.get('email'))}</email>\n"
            f"    <hc-contact-id>{_e(c.get('hc_contact_id'))}</hc-contact-id>\n"
            "  </contact>\n"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rep-company template-version="{CO_TEMPLATE_VERSION}">\n'
        f"  <company-id>{_e(data.get('company_id'))}</company-id>\n"
        f"  <company-name>{_e(data.get('applicant'))}</company-name>\n"
        f"{contact_xml}"
        "</rep-company>\n"
    )


def build_rt_xml(data: dict) -> str:
    """REQ-005/006: REP Regulatory Transaction XML (v5.1.0).

    The resolved activity type (CV code + label) and the dossier/company
    identifiers populate the RT template.
    """
    code = str(data.get("activity_type", "") or "").strip()
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rep-transaction template-version="{RT_TEMPLATE_VERSION}" '
        f'template-date="{RT_TEMPLATE_DATE}">\n'
        f"  <dossier-id>{_e(data.get('dossier_id'))}</dossier-id>\n"
        f"  <company-id>{_e(data.get('company_id'))}</company-id>\n"
        f'  <regulatory-activity-type code="{_e(code)}">'
        f"{_e(activity_type_label(code))}</regulatory-activity-type>\n"
        f"  <regulatory-activity-lead>{_e(data.get('activity_lead'))}"
        "</regulatory-activity-lead>\n"
        f"  <sequence>{_e(data.get('sequence'))}</sequence>\n"
        "</rep-transaction>\n"
    )


def build_pi_xml(data: dict) -> str:
    """REQ-006: REP Product Information XML (template 2024-02-12)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rep-product-information template-version="{PI_TEMPLATE_VERSION}">\n'
        f"  <dossier-id>{_e(data.get('dossier_id'))}</dossier-id>\n"
        f"  <product-name>{_e(data.get('drug_product'))}</product-name>\n"
        f"  <din>{_e(data.get('din'))}</din>\n"
        "</rep-product-information>\n"
    )


def build_ca_regional_xml(data: dict) -> str:
    """REQ-006/043: the eCTD CA-regional backbone metadata for a drug ANDS.

    The SAME single-entry REP identifiers (dossier/company/activity) populate
    this backbone — no re-keying. Metadata lives under m1/ca/, never in a
    device 1.04/1.05 folder.
    """
    code = str(data.get("activity_type", "") or "").strip()
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<ectd-ca-regional schema-version="{CA_MODULE1_SCHEMA_VERSION}">\n'
        "  <transaction-metadata>\n"
        f"    <dossier-id>{_e(data.get('dossier_id'))}</dossier-id>\n"
        f"    <company-id>{_e(data.get('company_id'))}</company-id>\n"
        f'    <regulatory-activity-type code="{_e(code)}">'
        f"{_e(activity_type_label(code))}</regulatory-activity-type>\n"
        f"    <sequence>{_e(data.get('sequence'))}</sequence>\n"
        "  </transaction-metadata>\n"
        "</ectd-ca-regional>\n"
    )


def build_cover_letter(data: dict) -> str:
    """REQ-009/043: sponsor-authored cover letter from the PORTAL's OWN template.

    HC provides only the placement slot (heading 1.0); this is the portal's
    template with the Dossier ID auto-populated — no re-keying, no HC form.
    """
    return (
        "Health Canada — Cover Letter\n"
        "============================\n\n"
        f"Sponsor:        {data.get('applicant', '').strip()}\n"
        f"Dossier ID:     {data.get('dossier_id', '').strip()}\n"
        f"Company ID:     {data.get('company_id', '').strip()}\n"
        f"Drug product:   {data.get('drug_product', '').strip()}\n"
        f"Activity type:  {activity_type_label(data.get('activity_type', ''))}\n"
        f"Sequence:       {data.get('sequence', '').strip()}\n\n"
        "This cover letter accompanies the regulatory transaction identified by "
        f"Dossier ID {data.get('dossier_id', '').strip()}.\n"
    )


# ---------------------------------------------------------------------------
# Single-entry transaction assembly (REQ-043, ties REQ-001/005/006 together)
# ---------------------------------------------------------------------------

# Required fields to assemble a REP transaction.
ASSEMBLY_FIELDS = {
    "applicant": "Applicant / company name",
    "company_id": "Company ID",
    "dossier_id": "Dossier ID",
    "activity_type": "Regulatory activity type",
    "sequence": "Sequence number",
    "drug_product": "Drug product name",
}


def validate_assembly(data: dict) -> list:
    """All errors that would block assembling a REP transaction (REQ-001/005/042)."""
    errors: list = []

    def add(rule: str, message: str):
        errors.append({"rule": rule, "message": message})

    vals = {f: str(data.get(f, "") or "").strip() for f in ASSEMBLY_FIELDS}
    for field_name, label in ASSEMBLY_FIELDS.items():
        if not vals[field_name]:
            add(f"{field_name}_required", f"{label} is required")

    # Identifier formats (only meaningful when present).
    errors.extend(validate_identifiers(data))

    # Activity type must be in HC's controlled vocabulary (I08).
    if vals["activity_type"] and not is_valid_activity_type(vals["activity_type"]):
        add("activity_type_cv",
            f"'{vals['activity_type']}' is not in HC's regulatory-activity "
            "controlled vocabulary (mirrors rule I08)")

    return errors


def assemble_transaction(data: dict, now: datetime | None = None) -> dict:
    """REQ-043: enter REP CO/RT/PI identifiers ONCE; emit every artifact.

    Returns ``{"valid": bool, "errors": [...], "transaction": {...}}``. When
    valid, ``transaction`` carries the CO/RT/(PI) REP XML with their immutable
    machine-generated filenames, the ca-regional.xml backbone (same identifiers),
    and the portal's own cover letter — all from a single set of inputs.

    The drug ANDS path explicitly does NOT emit the device-only AI template or
    use the 1.04/1.05 placement (REQ-006).
    """
    errors = validate_assembly(data)
    if errors:
        return {"valid": False, "errors": errors, "transaction": None}

    dossier_id = str(data.get("dossier_id", "")).strip()
    company_id = str(data.get("company_id", "")).strip()
    pi_required = bool(data.get("pi_required"))

    transaction = {
        "co": {
            "filename": co_filename(company_id, now),
            "xml": build_co_xml(data),
            "template_version": CO_TEMPLATE_VERSION,
            "immutable": True,
        },
        "rt": {
            "filename": rt_filename(dossier_id, now),
            "xml": build_rt_xml(data),
            "template_version": RT_TEMPLATE_VERSION,
            "immutable": True,
        },
        "pi": None,
        "ca_regional": {
            "path": CA_REGIONAL_PATH,
            "xml": build_ca_regional_xml(data),
            "schema_version": CA_MODULE1_SCHEMA_VERSION,
        },
        "cover_letter": {
            "leaf": COVER_LETTER_LEAF,
            "text": build_cover_letter(data),
            "source": "portal-template",
        },
        # Drug ANDS path: device-only artifacts are NOT produced.
        "uses_ai_template": False,
        "rep_metadata_path": CA_REGIONAL_PATH,
    }
    if pi_required:
        transaction["pi"] = {
            "filename": pi_filename(dossier_id, now),
            "xml": build_pi_xml(data),
            "template_version": PI_TEMPLATE_VERSION,
            "immutable": True,
        }

    return {"valid": True, "errors": [], "transaction": transaction}


# ---------------------------------------------------------------------------
# Dossier-ID request workflow + 8-week MAXIMUM lead-time rule (REQ-002)
# ---------------------------------------------------------------------------
#
# HC's 8-week rule is a MAXIMUM ("request a Dossier ID no MORE than 8 weeks
# before the intended first-filing date"), NOT a minimum lead-time gate. We
# therefore WARN when a request is placed too early and NEVER gate a request
# placed within the window. Most ANDS work is follow-up sequences that REUSE an
# existing Dossier ID (no new request), with an optional DSTS-IA lookup.

DOSSIER_ID_MAX_LEAD_WEEKS = 8
DOSSIER_ID_MAX_LEAD_DAYS = DOSSIER_ID_MAX_LEAD_WEEKS * 7   # 56

# Existing-dossier lookup contact for continuing sequences (DSTS-IA).
DSTS_IA_LOOKUP_CONTACT = "client.information@hc-sc.gc.ca"

# Common request-form fields presented for a NEW Dossier ID request.
_REQUEST_FIELDS = [
    "company_id", "company_name", "product_name",
    "activity_type", "intended_first_filing_date",
]

# Product-type / activity branches for a Dossier ID request. Each carries the
# HC prefix convention, the accepted digit lengths, and the HC request form.
# The Master File branch splits by transaction format: e+6 (eCTD) vs f+7
# (non-eCTD).
DOSSIER_REQUEST_BRANCHES = {
    "pharmaceutical": {
        "label": "Pharmaceutical / biologic (eCTD)",
        "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for pharmaceutical/biologic dossiers",
        "fields": list(_REQUEST_FIELDS),
    },
    "pharmaceutical-clinical-trial": {
        "label": "Pharmaceutical clinical trial (CTA)",
        "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for pharmaceutical/biologic dossiers",
        "fields": list(_REQUEST_FIELDS),
    },
    "biologic-clinical-trial": {
        "label": "Biologic clinical trial (CTA)",
        "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for pharmaceutical/biologic dossiers",
        "fields": list(_REQUEST_FIELDS),
    },
    "veterinary": {
        "label": "Veterinary drug",
        "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for veterinary drugs",
        "fields": list(_REQUEST_FIELDS),
    },
    "biocide": {
        "label": "Biocide",
        "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for biocides",
        "fields": list(_REQUEST_FIELDS),
    },
    "medical-device": {
        "label": "Medical device",
        "prefix": "m", "digits": (6, 7),
        "form": "Dossier ID request form for medical devices",
        "fields": list(_REQUEST_FIELDS),
    },
    "master-file-ectd": {
        "label": "Master File (eCTD)",
        "prefix": "e", "digits": (6,),
        "form": "Master File Dossier ID request form (eCTD)",
        "fields": list(_REQUEST_FIELDS),
    },
    "master-file-non-ectd": {
        "label": "Master File (non-eCTD)",
        "prefix": "f", "digits": (7,),
        "form": "Master File Dossier ID request form (non-eCTD)",
        "fields": list(_REQUEST_FIELDS),
    },
}


def _parse_iso_date(value):
    """Parse a YYYY-MM-DD date; return a ``date`` or None when unparseable."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def assess_dossier_id_lead_time(request_date, first_filing_date) -> dict:
    """REQ-002: HC's 8-week lead time is a MAXIMUM, not a minimum gate.

    Warn ONLY when the request is placed MORE than 8 weeks before the intended
    first-filing date. A request placed within (or exactly at) the window is
    never flagged or gated. Unparseable dates yield a non-assessable result
    (still never a gate).
    """
    req = _parse_iso_date(request_date)
    filing = _parse_iso_date(first_filing_date)
    basis = (f"HC {DOSSIER_ID_MAX_LEAD_WEEKS}-week MAXIMUM lead time "
             "(warn-only; never gates)")
    if req is None or filing is None:
        return {"assessable": False, "days_ahead": None, "weeks_ahead": None,
                "too_early": False, "warning": None,
                "max_lead_weeks": DOSSIER_ID_MAX_LEAD_WEEKS, "basis": basis}
    days_ahead = (filing - req).days
    weeks_ahead = round(days_ahead / 7, 1)
    too_early = days_ahead > DOSSIER_ID_MAX_LEAD_DAYS
    warning = None
    if too_early:
        warning = (
            f"Dossier ID requested {weeks_ahead} weeks before the intended "
            f"first-filing date; HC asks that it be requested no more than "
            f"{DOSSIER_ID_MAX_LEAD_WEEKS} weeks in advance (a MAXIMUM, not a "
            "minimum lead time).")
    return {"assessable": True, "days_ahead": days_ahead,
            "weeks_ahead": weeks_ahead, "too_early": too_early,
            "warning": warning, "max_lead_weeks": DOSSIER_ID_MAX_LEAD_WEEKS,
            "basis": basis}


def _dossier_id_conforms(value, prefix, accepted_digits=(6, 7)) -> bool:
    """REQ-002: prefix + per-branch digit-count check.

    Builds on ``is_valid_dossier_id`` (which guarantees ``<prefix>`` + 6/7
    digits) and additionally requires the digit count to be one the branch
    accepts — so a Master File ``e+7`` (must be e+6) or ``f+6`` (must be f+7) is
    correctly rejected, while the generic drug/device branches keep 6 OR 7.
    """
    value = str(value or "").strip()
    if not is_valid_dossier_id(value, prefix):
        return False
    return (len(value) - 1) in set(accepted_digits or (6, 7))


def request_dossier_id(data: dict, now: datetime | None = None) -> dict:
    """REQ-002: open a NEW branched Dossier ID request.

    Validates the product-type/activity branch, attaches the 8-week MAX lead
    time assessment (warn-only), and returns a ``pending`` request that tracks
    its status until HC returns an assigned ID. ``now`` is accepted for
    symmetry with the other stampers (unused today).
    """
    branch_key = str((data or {}).get("branch", "") or "").strip()
    branch = DOSSIER_REQUEST_BRANCHES.get(branch_key)
    if branch is None:
        return {"valid": False, "request": None, "errors": [{
            "rule": "branch_unknown",
            "message": (f"'{branch_key}' is not a known Dossier ID request "
                        f"branch ({', '.join(DOSSIER_REQUEST_BRANCHES)})")}]}

    lead = assess_dossier_id_lead_time(
        (data or {}).get("request_date"),
        (data or {}).get("intended_first_filing_date"))
    request = {
        "branch": branch_key,
        "label": branch["label"],
        "prefix": branch["prefix"],
        "accepted_digits": list(branch["digits"]),
        "form": branch["form"],
        "fields": list(branch["fields"]),
        "status": "pending",            # awaiting an HC-assigned Dossier ID
        "assigned_dossier_id": None,
        "lead_time": lead,
        "warnings": [lead["warning"]] if lead["warning"] else [],
    }
    return {"valid": True, "request": request, "errors": []}


def resolve_dossier_id(data: dict, now: datetime | None = None) -> dict:
    """REQ-002: REUSE an existing Dossier ID for a continuing sequence, else
    open a new branched request.

    A continuing sequence in the same format reuses the stored Dossier ID with
    NO new request (and offers the DSTS-IA lookup when the stored ID is
    unknown). Otherwise this opens a new request via ``request_dossier_id``.
    """
    data = data or {}
    branch_key = str(data.get("branch", "") or "").strip()
    branch = DOSSIER_REQUEST_BRANCHES.get(branch_key)
    prefix = (branch["prefix"] if branch
              else str(data.get("dossier_prefix", "e") or "e").strip() or "e")
    accepted = branch["digits"] if branch else (6, 7)
    existing = str(data.get("existing_dossier_id", "") or "").strip()

    if existing and _dossier_id_conforms(existing, prefix, accepted):
        return {
            "action": "reuse",
            "valid": True,
            "errors": [],
            "dossier_id": existing,
            "new_request_required": False,
            "request": None,
            "dsts_ia_lookup": DSTS_IA_LOOKUP_CONTACT,
            "note": ("Continuing sequence in the same format — reuse the stored "
                     "Dossier ID; no new HC request. Use the DSTS-IA lookup if "
                     "the stored ID is unknown."),
        }

    opened = request_dossier_id(data, now)
    return {
        "action": "request",
        "valid": opened["valid"],
        "errors": opened["errors"],
        "dossier_id": None,
        "new_request_required": True,
        "request": opened["request"],
        "dsts_ia_lookup": DSTS_IA_LOOKUP_CONTACT,
    }


def record_dossier_id_assignment(request: dict, assigned_id: str) -> dict:
    """REQ-002: transition a pending request to 'assigned' once HC returns an ID.

    Validates the HC-assigned ID against the request branch's prefix/format. On
    success the request status flips to 'assigned'; on a format mismatch the
    request stays 'pending' and the assignment is rejected.
    """
    request = dict(request or {})
    prefix = str(request.get("prefix", "e") or "e")
    accepted = request.get("accepted_digits") or (6, 7)
    assigned = str(assigned_id or "").strip()
    if not _dossier_id_conforms(assigned, prefix, accepted):
        return {"valid": False, "request": request,
                "error": (f"HC-assigned Dossier ID '{assigned}' is not a valid "
                          f"'{prefix}' + {'/'.join(map(str, accepted))}-digit "
                          "identifier")}
    request["assigned_dossier_id"] = assigned
    request["status"] = "assigned"
    request.setdefault("warnings", [])
    return {"valid": True, "request": request, "error": None}
