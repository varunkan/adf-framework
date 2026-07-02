"""Drug shortage / discontinuation reports + DEL linkage — pure.

Health Canada mandatory reporting (Food and Drug Regulations
C.01.014.8–C.01.014.12 + the shortages tier protocol), encoded as pure
date arithmetic like :mod:`hc_calendar` / :mod:`noa`:

* A **Tier-3 shortage** must be reported within
  :data:`REPORT_WINDOW_DAYS` (5) days of the sponsor becoming aware of
  it. Tier 1/2 shortages carry no mandatory window here.
* A **discontinuation** must be reported at least
  :data:`DISCONTINUATION_LEAD_MONTHS` (6) months before the
  discontinuation date — or, when the decision lands inside that lead,
  within 5 days of the decision. Compliance is the LATER prong.

``with_status`` derives ``report_deadline`` and an ``is_late`` flag vs
``as_of`` (using ``reported_at`` when filed, else ``as_of`` itself).

A Drug Establishment Licence (DEL) linkage ties a dossier to a DEL
number and the establishment sites it covers.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import hc_calendar, noa

KIND_SHORTAGE = "shortage"
KIND_DISCONTINUATION = "discontinuation"
KINDS = (KIND_SHORTAGE, KIND_DISCONTINUATION)

TIERS = (1, 2, 3)
REPORT_WINDOW_DAYS = 5          # C.01.014.9(2): 5 days from awareness
DISCONTINUATION_LEAD_MONTHS = 6  # C.01.014.10: 6 months ahead


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _iso_or_error(data: dict, field: str, errors: list,
                  *, required: bool = False) -> str | None:
    raw = _s(data.get(field))
    if not raw:
        if required:
            errors.append({"rule": f"{field}_required",
                           "message": f"{field} is required"})
        return None
    try:
        return hc_calendar._as_date(raw).isoformat()
    except ValueError:
        errors.append({"rule": f"{field}_invalid",
                       "message": f"{field} must be an ISO date"})
        return None


def _tier(value) -> int | None:
    try:
        t = int(_s(value))
    except (TypeError, ValueError):
        return None
    return t if t in TIERS else None


def validate_record(data: dict) -> dict:
    """Validate + build a shortage/discontinuation report.

    Returns ``{"valid", "record"|"errors"}``. Tier 3 requires a reason;
    ``anticipated_end`` (optional) must not precede ``anticipated_start``.
    """
    data = data or {}
    errors = []
    if not _s(data.get("dossier_id")):
        errors.append({"rule": "dossier_id_required",
                       "message": "dossier_id is required"})
    if not _s(data.get("din")):
        errors.append({"rule": "din_required",
                       "message": "the DIN is required"})
    kind = _s(data.get("kind")).lower()
    if kind not in KINDS:
        errors.append({"rule": "kind_invalid",
                       "message": "kind must be one of " + ", ".join(KINDS)})
    tier = _tier(data.get("tier"))
    if tier is None:
        errors.append({"rule": "tier_invalid",
                       "message": "tier must be 1, 2 or 3"})
    reason = _s(data.get("reason"))
    if tier == 3 and not reason:
        errors.append({"rule": "tier3_reason_required",
                       "message": "a Tier-3 report must state the reason"})
    start = _iso_or_error(data, "anticipated_start", errors, required=True)
    end = _iso_or_error(data, "anticipated_end", errors)
    if start and end and end < start:
        errors.append({"rule": "end_before_start",
                       "message": "anticipated_end precedes "
                                  "anticipated_start"})
    became_aware = _iso_or_error(data, "became_aware", errors)
    reported_at = _iso_or_error(data, "reported_at", errors)
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "record": {
        "dossier_id": _s(data.get("dossier_id")), "din": _s(data.get("din")),
        "kind": kind, "tier": tier, "reason": reason or None,
        "anticipated_start": start, "anticipated_end": end,
        "became_aware": became_aware, "reported_at": reported_at}}


def report_deadline(record: dict) -> str | None:
    """The latest compliant report date for the record, or ``None``.

    Shortage: Tier 3 only — 5 days from becoming aware. Discontinuation:
    the later of (start − 6 months) and (awareness + 5 days), i.e.
    meeting either prong is compliant.
    """
    aware = record.get("became_aware") or record.get("reported_at")
    five_days = (hc_calendar._as_date(aware)
                 + timedelta(days=REPORT_WINDOW_DAYS)).isoformat() \
        if aware else None
    if record.get("kind") == KIND_SHORTAGE:
        return five_days if record.get("tier") == 3 else None
    lead = noa.add_months(record["anticipated_start"],
                          -DISCONTINUATION_LEAD_MONTHS).isoformat()
    return max(lead, five_days) if five_days else lead


def with_status(record: dict, as_of=None) -> dict:
    """Record + computed ``report_deadline`` / ``is_late`` / ``as_of``.

    Lateness compares the filing date (``reported_at`` when present,
    else ``as_of`` — the report is still outstanding) to the deadline.
    """
    on = hc_calendar._as_date(as_of) if _s(as_of) else date.today()
    deadline = report_deadline(record)
    effective = record.get("reported_at") or on.isoformat()
    view = dict(record)
    view["as_of"] = on.isoformat()
    view["report_deadline"] = deadline
    view["is_late"] = bool(deadline) and effective > deadline
    return view


# ---------------------------------------------------------------------------
# DEL linkage
# ---------------------------------------------------------------------------
def validate_del_link(data: dict) -> dict:
    """Validate + build a Drug Establishment Licence linkage record.

    ``{dossier_id, del_number, sites[]}`` — sites are trimmed and empties
    dropped. Returns ``{"valid", "record"|"errors"}``.
    """
    data = data or {}
    errors = []
    if not _s(data.get("dossier_id")):
        errors.append({"rule": "dossier_id_required",
                       "message": "dossier_id is required"})
    if not _s(data.get("del_number")):
        errors.append({"rule": "del_number_required",
                       "message": "the DEL number is required"})
    sites = [_s(s) for s in (data.get("sites") or []) if _s(s)]
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "record": {
        "dossier_id": _s(data.get("dossier_id")),
        "del_number": _s(data.get("del_number")), "sites": sites}}
