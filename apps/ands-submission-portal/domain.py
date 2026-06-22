"""
ANDS Submission Portal — core domain logic (MVP slice).

Pure, dependency-free (Python 3 standard library only) implementation of the
ANDS submission-intake validation rules. Everything here is deterministic and
unit-testable; the HTTP/API/UI layer in server.py is a thin shell over these
functions.

Scope is the bounded MVP defined in specs/ands-submission-portal/mvp-scope.md:
core ANDS submission intake + the validation rules that make an intake
"first-pass clean" — Dossier-ID format, sequence format, the per-dossier
sequence lifecycle, and required-field / email / submission-type checks.

Requirement traceability tags (REQ-xxx) reference
specs/ands-submission-portal/requirements.md.
"""

from __future__ import annotations

import re


# Email shape — deliberately permissive: a non-empty local part, an "@", a
# domain with at least one dot, and no whitespace.
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# Dossier ID for the MVP is specifically a lowercase 'e' followed by 6 or 7
# digits (pharmaceutical/biologic eCTD ANDS) — REQ-002 / REQ-042.
DOSSIER_ID_RE = re.compile(r"e[0-9]{6,7}")

# Sequence folder: exactly four digits, 0000-9999 — REQ-016 / REQ-042.
SEQUENCE_RE = re.compile(r"[0-9]{4}")

# The submission type is fixed for the MVP.
MVP_SUBMISSION_TYPE = "ANDS"

# Required, non-empty intake fields with human-readable labels.
INTAKE_FIELDS = {
    "applicant": "Applicant / company name",
    "drug_product": "Drug product name",
    "dossier_id": "Dossier ID",
    "sequence": "Sequence number",
    "contact_email": "Contact email",
}


def is_valid_dossier_id(value: str) -> bool:
    """MVP Dossier-ID rule: lowercase 'e' + 6 or 7 digits (e.g. e123456)."""
    return bool(DOSSIER_ID_RE.fullmatch(str(value or "").strip()))


def is_valid_sequence(value: str) -> bool:
    """MVP sequence-format rule: exactly four digits (0000-9999)."""
    return bool(SEQUENCE_RE.fullmatch(str(value or "").strip()))


def is_valid_email(value: str) -> bool:
    """MVP contact-email rule: must look like an email address."""
    return bool(EMAIL_RE.fullmatch(str(value or "").strip()))


def next_expected_sequence(prior_sequences) -> str:
    """REQ-016: the next sequence in a dossier's lifecycle.

    The first accepted sequence MUST be 0000; each subsequent one is exactly the
    previous + 1 (no gaps, no duplicates). Given the dossier's already-accepted
    sequences, return the only sequence that may be accepted next.
    """
    nums = [int(s) for s in prior_sequences if SEQUENCE_RE.fullmatch(str(s))]
    if not nums:
        return "0000"
    return f"{max(nums) + 1:04d}"


def validate_intake(data: dict, prior_sequences=()) -> list:
    """Validate one ANDS submission against ALL MVP rules.

    Returns a list of {"rule", "message"} dicts — one per failing rule, every
    failing rule (never short-circuits). An empty list means the submission is
    acceptable. ``prior_sequences`` is the dossier's already-accepted sequences,
    used for the lifecycle check.
    """
    errors: list = []

    def add(rule: str, message: str):
        errors.append({"rule": rule, "message": message})

    vals = {f: str(data.get(f, "") or "").strip() for f in INTAKE_FIELDS}
    submission_type = str(data.get("submission_type", "") or "").strip()

    # 1. Required fields present and non-empty.
    for field_name, label in INTAKE_FIELDS.items():
        if not vals[field_name]:
            add(f"{field_name}_required", f"{label} is required")

    # 2. Dossier-ID format.
    if vals["dossier_id"] and not is_valid_dossier_id(vals["dossier_id"]):
        add("dossier_id_format",
            "Dossier ID must be a lowercase 'e' followed by 6 or 7 digits "
            "(e.g. e123456 or e1234567)")

    # 3. Submission type must equal ANDS.
    if submission_type != MVP_SUBMISSION_TYPE:
        add("submission_type",
            f"Submission type must be '{MVP_SUBMISSION_TYPE}'")

    # 4. Sequence format (exactly 4 digits).
    seq_ok = is_valid_sequence(vals["sequence"])
    if vals["sequence"] and not seq_ok:
        add("sequence_format",
            "Sequence number must be exactly 4 digits (0000-9999)")

    # 5. Contact email shape.
    if vals["contact_email"] and not is_valid_email(vals["contact_email"]):
        add("contact_email_format",
            "Contact email is not a valid email address")

    # 6. Sequence lifecycle — only meaningful once the dossier ID and the
    #    sequence are themselves well-formed. The first accepted sequence must
    #    be 0000; each later one exactly previous + 1 (catches gaps AND dupes).
    if is_valid_dossier_id(vals["dossier_id"]) and seq_ok:
        expected = next_expected_sequence(prior_sequences)
        if vals["sequence"] != expected:
            add("sequence_lifecycle",
                f"Sequence {vals['sequence']} is out of order for this dossier; "
                f"the expected next sequence is {expected}")

    return errors
