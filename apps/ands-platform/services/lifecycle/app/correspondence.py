"""HC correspondence hub domain — pure (REQ-112).

Logs Health Canada correspondence (SDN/NOD/NON/NOC/SAL/clarifax/queries/letters)
linked to a dossier, with direction. Pairs with the DSTS lifecycle: the same
notice kinds drive lifecycle transitions (REQ-096).
"""

from __future__ import annotations

KINDS = {
    "SDN": "Screening Deficiency Notice",
    "SAL": "Screening Acceptance Letter",
    "SRL": "Screening Rejection Letter",
    "NOD": "Notice of Deficiency",
    "NON": "Notice of Non-compliance",
    "NOC": "Notice of Compliance",
    "clarifax": "Clarification request (clarifax)",
    "query": "Review query",
    "commitment": "Post-NOC commitment",
    "letter": "General correspondence",
}
DIR_INBOUND = "inbound"     # HC → sponsor
DIR_OUTBOUND = "outbound"   # sponsor → HC
DIRECTIONS = (DIR_INBOUND, DIR_OUTBOUND)


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def validate_correspondence(data: dict) -> dict:
    """Validate + clean a correspondence record. ``{valid, record|errors}``."""
    data = data or {}
    errors = []
    kind = _s(data.get("kind"))
    if kind not in KINDS:
        errors.append({"rule": "kind_invalid",
                       "message": "kind must be one of " + ", ".join(KINDS)})
    if not _s(data.get("dossier_id")):
        errors.append({"rule": "dossier_id_required",
                       "message": "dossier_id is required"})
    if not _s(data.get("subject")):
        errors.append({"rule": "subject_required",
                       "message": "a subject is required"})
    direction = _s(data.get("direction")).lower() or DIR_INBOUND
    if direction not in DIRECTIONS:
        errors.append({"rule": "direction_invalid",
                       "message": "direction must be inbound or outbound"})
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "record": {
        "dossier_id": _s(data.get("dossier_id")), "kind": kind,
        "kind_label": KINDS[kind], "subject": _s(data.get("subject")),
        "body": _s(data.get("body")), "direction": direction,
        "received_at": _s(data.get("received_at")),
        "reference": _s(data.get("reference"))}}
