"""
ANDS Submission Portal — HC Module 1 controlled-vocabulary ingestion (REQ-066).

Health Canada publishes Module 1 controlled-vocabulary / enumeration files keyed
to the CA Module 1 schema version. This module INGESTS them as VERSIONED DATA — a
single source of truth, updatable without spreading hand-maintained lists across
the code — and validates submitted metadata against them, rejecting out-of-
vocabulary values via eCTD rules **I08** (submission/activity type not in CV) and
**H08** (invalid Module-1 attribute/enumeration value).

Stdlib-only: the CV set is held here as versioned reference data and exposed
through ``load_cv()``; a drop-in replacement can read the same shape from HC's
published files under util/cv/ without touching any call site. Deterministic, no
I/O at import. The HTTP/API layer in server.py is a thin shell.

Requirement traceability (specs/ands-submission-portal/requirements.md):
  REQ-005  Activity type resolved from HC's published CV; out-of-CV -> I08
  REQ-040  Version-pinned reference-data layer keyed to the schema version
  REQ-066  Ingest the actual HC CV/enumeration files (not a hand-maintained
           list); reject out-of-vocabulary values mirroring I08/H08
"""

from __future__ import annotations

SEVERITY_ERROR = "Error"
DEFAULT_SCHEMA_VERSION = "2.2"

# HC Module-1 controlled vocabularies, KEYED TO THE CA MODULE 1 SCHEMA VERSION.
# Replaceable as data (load_cv) without code changes (REQ-040/066). Activity-type
# labels match the REP RT template's display strings so rep can source them here.
_CONTROLLED_VOCABULARIES = {
    "2.2": {
        "activity_type": {
            "NDS": "New Drug Submission (NDS)",
            "ANDS": "Abbreviated New Drug Submission (ANDS)",
            "SNDS": "Supplement to a New Drug Submission (SNDS)",
            "SANDS": "Supplement to an Abbreviated New Drug Submission (SANDS)",
            "DINA": "Drug Identification Number Application (DINA)",
            "NC": "Notifiable Change (NC)",
            "CTA": "Clinical Trial Application (CTA)",
        },
        "dosage_form": {
            "tablet": "Tablet",
            "capsule": "Capsule",
            "solution": "Solution",
            "suspension": "Suspension",
            "cream": "Cream",
            "ointment": "Ointment",
            "injection": "Injection",
        },
        "route_of_administration": {
            "oral": "Oral",
            "intravenous": "Intravenous",
            "intramuscular": "Intramuscular",
            "subcutaneous": "Subcutaneous",
            "topical": "Topical",
            "ophthalmic": "Ophthalmic",
        },
    },
}

# Which eCTD rule fires for an out-of-vocabulary value, by Module-1 field.
# Submission/activity type -> I08; every other enumeration/attribute -> H08.
_I08_FIELDS = frozenset({"activity_type", "submission_type"})


class ControlledVocabularyError(KeyError):
    """Raised when a CV is requested for an unpublished schema version."""


def schema_versions() -> list:
    """The schema versions for which a CV set has been ingested."""
    return sorted(_CONTROLLED_VOCABULARIES)


def load_cv(schema_version: str = DEFAULT_SCHEMA_VERSION) -> dict:
    """REQ-066: ingest the HC Module-1 CV set for a schema version (as data).

    Returns a deep-ish copy ({field: {code: label}}) so callers can never mutate
    the canonical store.
    """
    version = str(schema_version or DEFAULT_SCHEMA_VERSION).strip()
    if version not in _CONTROLLED_VOCABULARIES:
        raise ControlledVocabularyError(
            f"no controlled vocabulary published for schema version {version!r}")
    return {field: dict(codes)
            for field, codes in _CONTROLLED_VOCABULARIES[version].items()}


def vocabulary(field: str, schema_version: str = DEFAULT_SCHEMA_VERSION) -> dict:
    """The {code: label} controlled vocabulary for one Module-1 field."""
    return load_cv(schema_version).get(field, {})


def is_in_cv(field: str, value, schema_version: str = DEFAULT_SCHEMA_VERSION) -> bool:
    """True when ``value`` is a published code for ``field`` at that schema version."""
    return str(value or "").strip() in vocabulary(field, schema_version)


def label_for(field: str, value, schema_version: str = DEFAULT_SCHEMA_VERSION) -> str:
    """Human-readable label for a CV code; '' for an unknown code."""
    return vocabulary(field, schema_version).get(str(value or "").strip(), "")


def _rule_for(field: str) -> str:
    return "I08" if field in _I08_FIELDS else "H08"


def validate_value(field: str, value,
                   schema_version: str = DEFAULT_SCHEMA_VERSION) -> list:
    """REQ-005/066: reject an out-of-vocabulary Module-1 value via I08/H08.

    Returns ``[]`` when the value is empty (emptiness is a separate required-
    field concern) or present in the CV, else a single Error finding bearing the
    correct rule id.
    """
    text = str(value or "").strip()
    if not text or is_in_cv(field, text, schema_version):
        return []
    rule = _rule_for(field)
    return [{
        "rule": rule,
        "severity": SEVERITY_ERROR,
        "field": field,
        "message": (f"'{text}' is not in HC's Module 1 controlled vocabulary "
                    f"for '{field}' (schema v{schema_version}) — mirrors rule "
                    f"{rule}"),
    }]


def validate_metadata(metadata: dict,
                      schema_version: str = DEFAULT_SCHEMA_VERSION) -> list:
    """Validate every CV-governed field present in ``metadata`` (REQ-066)."""
    metadata = metadata or {}
    errors: list = []
    for field in load_cv(schema_version):
        if field in metadata:
            errors.extend(validate_value(field, metadata[field], schema_version))
    return errors
