"""Registration registry domain — pure (REQ-111).

A registration is a marketed-product record (product × country × dossier × DIN).
The status state machine and the post-NOC Right-to-Sell obligation live here; the
fee *amount* is the fees service's job — this links the obligation by drug type
and the statutory October-1 due date.
"""

from __future__ import annotations

from datetime import date, datetime

STATUS_SUBMITTED = "Submitted"
STATUS_NOC = "NOC-Issued"
STATUS_MARKETED = "Marketed"
STATUS_SUSPENDED = "Suspended"
STATUS_CANCELLED = "Cancelled"
STATUSES = (STATUS_SUBMITTED, STATUS_NOC, STATUS_MARKETED, STATUS_SUSPENDED,
            STATUS_CANCELLED)

_TRANSITIONS = {
    STATUS_SUBMITTED: {STATUS_NOC, STATUS_CANCELLED},
    STATUS_NOC: {STATUS_MARKETED, STATUS_SUSPENDED, STATUS_CANCELLED},
    STATUS_MARKETED: {STATUS_SUSPENDED, STATUS_CANCELLED},
    STATUS_SUSPENDED: {STATUS_MARKETED, STATUS_CANCELLED},
    STATUS_CANCELLED: set(),
}

DRUG_TYPES = ("prescription", "non-prescription", "disinfectant", "biocide")
# a Right-to-Sell obligation exists once the product is marketable (post-NOC)
_RIGHT_TO_SELL_STATUSES = {STATUS_NOC, STATUS_MARKETED, STATUS_SUSPENDED}


def _s(v) -> str:
    return str(v or "").strip()


def new_registration(data: dict) -> dict:
    """Validate + clean a registration. ``{valid, registration|errors}``."""
    data = data or {}
    errors = []
    product = _s(data.get("product"))
    country = _s(data.get("country")) or "CA"
    dossier_id = _s(data.get("dossier_id"))
    din = _s(data.get("din"))
    drug_type = _s(data.get("drug_type")).lower()
    if not product:
        errors.append({"rule": "product_required",
                       "message": "product is required"})
    if not dossier_id:
        errors.append({"rule": "dossier_id_required",
                       "message": "dossier_id is required"})
    if drug_type and drug_type not in DRUG_TYPES:
        errors.append({"rule": "drug_type_invalid",
                       "message": "drug_type must be one of "
                                  + ", ".join(DRUG_TYPES)})
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "registration": {
        "product": product, "country": country, "dossier_id": dossier_id,
        "din": din, "drug_type": drug_type or None, "status": STATUS_SUBMITTED}}


def validate_status_transition(old: str, new: str) -> dict:
    new = _s(new)
    if new not in STATUSES:
        return {"valid": False, "rule": "status_unknown",
                "message": "status must be one of " + ", ".join(STATUSES)}
    if new not in _TRANSITIONS.get(old, set()):
        return {"valid": False, "rule": "status_illegal_transition",
                "message": f"cannot move a registration from {old} to {new}"}
    return {"valid": True}


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(_s(value)[:10])


def right_to_sell_obligation(registration: dict, as_of) -> dict:
    """The post-NOC Right-to-Sell obligation: statutory Oct-1 due date in the
    fiscal year of ``as_of``. Only applies once marketable (REQ-111 / REQ-037)."""
    status = registration.get("status")
    if status not in _RIGHT_TO_SELL_STATUSES:
        return {"applies": False,
                "reason": f"no Right-to-Sell obligation while {status}"}
    d = _as_date(as_of)
    fy_start = d.year if d.month >= 4 else d.year - 1
    due = date(fy_start, 10, 1)
    return {"applies": True, "drug_type": registration.get("drug_type"),
            "din": registration.get("din"), "due_date": due.isoformat(),
            "fiscal_year": f"{fy_start}-{(fy_start + 1) % 100:02d}",
            "fee_owner": "fees-service",
            "overdue": d > due}
