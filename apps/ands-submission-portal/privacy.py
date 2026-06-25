"""
ANDS Submission Portal — privacy: consent + data-subject rights (NFR-005).

PIPEDA is the FEDERAL BASELINE for express-consent capture and data-subject
access/correction handling. A configurable PROVINCIAL OVERLAY (Alberta /
British Columbia / Quebec PIPA, Ontario PHIPA) applies WHERE the activity is
wholly intra-provincial OR personal health information (PHI) is handled.

Every control carries an explicit ``basis`` tag from the REQ-067 vocabulary so
auditors are never misled about what Health Canada actually mandates: privacy
here is a PIPEDA / provincial obligation and a configurable VALUE-ADD — NOT a
Health Canada submission-preparation mandate.

Pure Python 3 standard library, deterministic (timestamps are injected, never
read from the clock here). The HTTP/API layer in server.py is a thin shell.

Requirement traceability (specs/ands-submission-portal/requirements.md):
  NFR-005  Express consent + data-subject access/correction; PIPEDA baseline
           with a configurable provincial overlay (AB/BC/QC PIPA, ON PHIPA)
  REQ-067  Every compliance control carries a 'basis' tag from a closed set
"""

from __future__ import annotations

# REQ-067 'basis' vocabulary — the closed set every compliance control tags with.
BASIS_HC_MANDATE = "HC-mandate"
BASIS_GC_DIRECTION = "GC-direction"
BASIS_PROVINCIAL = "provincial-privacy"
BASIS_PIPEDA = "PIPEDA"
BASIS_GMP = "GMP-best-practice"
BASIS_VALUE_ADD = "value-add"
BASIS_VALUES = (
    BASIS_HC_MANDATE, BASIS_GC_DIRECTION, BASIS_PROVINCIAL,
    BASIS_PIPEDA, BASIS_GMP, BASIS_VALUE_ADD,
)

# Federal baseline (PIPEDA): express consent + access/correction rights.
PIPEDA_BASELINE = {
    "regime": "PIPEDA",
    "law": "Personal Information Protection and Electronic Documents Act",
    "consent": "express",
    "data_subject_rights": ["access", "correction"],
    "basis": BASIS_PIPEDA,
}

# Configurable provincial overlay. Applies where the activity is wholly
# intra-provincial OR PHI is handled (PHIPA is health-information-specific).
PROVINCIAL_REGIMES = {
    "AB": {"law": "Alberta PIPA", "kind": "private-sector"},
    "BC": {"law": "British Columbia PIPA", "kind": "private-sector"},
    "QC": {"law": "Quebec Law 25 (Act respecting the protection of personal "
                  "information in the private sector)", "kind": "private-sector"},
    "ON": {"law": "Ontario PHIPA", "kind": "health-information"},
}

DATA_SUBJECT_REQUEST_KINDS = ("access", "correction")


def privacy_policy(province=None, intra_provincial=False, phi=False) -> dict:
    """NFR-005: the effective privacy regime for a tenant configuration.

    PIPEDA is always the baseline. A provincial overlay is layered ON TOP when
    a known province is configured AND the activity is wholly intra-provincial
    OR PHI is handled — otherwise PIPEDA alone governs. Carries REQ-067 basis
    tags and is explicitly marked ``hc_mandated=False``.
    """
    province = (str(province or "").strip().upper() or None)
    intra_provincial = bool(intra_provincial)
    phi = bool(phi)

    applies = bool(province and province in PROVINCIAL_REGIMES
                   and (intra_provincial or phi))
    overlay = None
    if applies:
        reg = PROVINCIAL_REGIMES[province]
        overlay = {
            "province": province,
            "law": reg["law"],
            "kind": reg["kind"],
            "basis": BASIS_PROVINCIAL,
            "applies_because": ("personal health information handled" if phi
                                else "wholly intra-provincial activity"),
        }

    effective = ["PIPEDA"] + ([overlay["law"]] if overlay else [])
    return {
        "baseline": dict(PIPEDA_BASELINE),
        "provincial_overlay": overlay,
        "overlay_applies": applies,
        "effective_regimes": effective,
        "consent": "express",
        "data_subject_rights": list(PIPEDA_BASELINE["data_subject_rights"]),
        "basis": (f"{BASIS_PIPEDA}+{BASIS_PROVINCIAL}" if applies
                  else BASIS_PIPEDA),
        "hc_mandated": False,
        "note": ("PIPEDA is the baseline; the provincial overlay is a "
                 "configurable value-add applied per tenant/province. This is a "
                 "privacy obligation, NOT a Health Canada submission mandate."),
    }


def capture_consent(data: dict, at: str) -> dict:
    """NFR-005: capture EXPRESS consent for sensitive (health/regulatory)
    personal data and retain the consent record.

    Returns ``{"valid","errors","record"}``. Implied/opt-out consent is
    rejected — sensitive personal data requires express consent under PIPEDA.
    """
    data = data or {}
    errors: list = []
    subject = str(data.get("subject", "") or "").strip()
    purpose = str(data.get("purpose", "") or "").strip()
    consent_type = str(data.get("consent_type", "express")
                       or "express").strip().lower()
    if not subject:
        errors.append({"rule": "subject_required",
                       "message": "Data subject is required"})
    if not purpose:
        errors.append({"rule": "purpose_required",
                       "message": "Purpose of collection is required"})
    if consent_type != "express":
        errors.append({"rule": "consent_must_be_express",
                       "message": ("Sensitive health/regulatory personal data "
                                   "requires EXPRESS consent under PIPEDA")})
    if errors:
        return {"valid": False, "errors": errors, "record": None}

    pol = privacy_policy(data.get("province"),
                         bool(data.get("intra_provincial")),
                         bool(data.get("phi")))
    record = {
        "subject": subject,
        "purpose": purpose,
        "consent_type": "express",
        "captured_at": str(at),
        "retained": True,
        "regimes": pol["effective_regimes"],
        "basis": pol["basis"],
    }
    return {"valid": True, "errors": [], "record": record}


def handle_data_subject_request(data: dict, at: str) -> dict:
    """NFR-005: open a data-subject ACCESS or CORRECTION request.

    Returns ``{"valid","errors","request"}``. The kind must be one of
    ``access`` / ``correction``; anything else is rejected.
    """
    data = data or {}
    errors: list = []
    kind = str(data.get("kind", "") or "").strip().lower()
    subject = str(data.get("subject", "") or "").strip()
    if kind not in DATA_SUBJECT_REQUEST_KINDS:
        errors.append({"rule": "kind_invalid",
                       "message": ("Data-subject request kind must be one of "
                                   f"{DATA_SUBJECT_REQUEST_KINDS}")})
    if not subject:
        errors.append({"rule": "subject_required",
                       "message": "Data subject is required"})
    if errors:
        return {"valid": False, "errors": errors, "request": None}

    pol = privacy_policy(data.get("province"),
                         bool(data.get("intra_provincial")),
                         bool(data.get("phi")))
    return {"valid": True, "errors": [], "request": {
        "kind": kind,
        "subject": subject,
        "received_at": str(at),
        "status": "open",
        "regimes": pol["effective_regimes"],
        "basis": pol["basis"],
    }}
