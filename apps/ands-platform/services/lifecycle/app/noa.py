"""Form V + Notice of Allegation register — pure (PM(NOC) Regulations).

A generic addressing a patent/CSP on the Patent Register files a Form V
allegation per patent. Allegations of non-infringement or invalidity
require a Notice of Allegation SERVED on the innovator; service opens the
innovator's 45-day window to commence a s.6 action, and a commenced action
triggers the 24-month statutory stay (s.7(1)(d)). Records are plain dicts;
clocks are computed with pure ``as_of`` date arithmetic like hc_calendar.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from . import hc_calendar

ALLEGATIONS = {
    "not_infringed": "No claim for the medicinal ingredient, formulation, "
                     "dosage form or use would be infringed",
    "invalid": "The patent or CSP is invalid or void",
    "accept_expiry": "NOC accepted to issue only on patent/CSP expiry",
    "no_claim": "The patent/CSP contains no claim addressed by the submission",
}
# only these allegations require an NOA served on the innovator (s.5(3))
NOA_REQUIRED = frozenset({"not_infringed", "invalid"})

ACTION_WINDOW_DAYS = 45   # s.6(1): innovator may sue within 45 days of service
STAY_MONTHS = 24          # s.7(1)(d): statutory stay from action commencement

STATUS_DRAFT = "draft"
STATUS_SERVED = "served"
STATUS_ACTION = "action_commenced"
STATUS_CLEAR = "clear"              # 45 days passed with no s.6 action
STATUS_STAY_RUNNING = "stay_running"
STATUS_RESOLVED = "resolved"


class NoaError(Exception):
    """An illegal NOA transition; carries the violated ``rule``."""

    def __init__(self, message: str, rule: str) -> None:
        super().__init__(message)
        self.rule = rule


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _iso(value) -> str:
    return hc_calendar._as_date(value).isoformat()


def add_months(start, months: int) -> date:
    """Pure month arithmetic with end-of-month clamping."""
    d = hc_calendar._as_date(start)
    m = d.month - 1 + int(months)
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def validate_allegation(data: dict) -> dict:
    """Validate + build a Form V record. ``{valid, record|errors}``."""
    data = data or {}
    errors = []
    if not _s(data.get("dossier_id")):
        errors.append({"rule": "dossier_id_required",
                       "message": "dossier_id is required"})
    if not _s(data.get("patent_number")):
        errors.append({"rule": "patent_number_required",
                       "message": "the patent/CSP number is required"})
    allegation = _s(data.get("allegation")).lower()
    if allegation not in ALLEGATIONS:
        errors.append({"rule": "allegation_invalid",
                       "message": "allegation must be one of "
                                  + ", ".join(ALLEGATIONS)})
    form_v = _s(data.get("form_v_date"))
    if not form_v:
        errors.append({"rule": "form_v_date_required",
                       "message": "form_v_date is required"})
    else:
        try:
            form_v = _iso(form_v)
        except ValueError:
            errors.append({"rule": "form_v_date_invalid",
                           "message": "form_v_date must be an ISO date"})
    if errors:
        return {"valid": False, "errors": errors}
    required = allegation in NOA_REQUIRED
    return {"valid": True, "record": {
        "dossier_id": _s(data.get("dossier_id")),
        "patent_number": _s(data.get("patent_number")),
        "allegation": allegation, "allegation_label": ALLEGATIONS[allegation],
        "form_v_date": form_v, "noa_required": required,
        "status": STATUS_DRAFT if required else STATUS_CLEAR,
        "served_date": None, "action_window_end": None, "action_date": None,
        "court_file": None, "stay_start": None, "stay_end": None,
        "resolved_at": None, "outcome": None,
        "history": [{"event": "form_v_filed", "at": form_v}]}}


def serve(record: dict, served_date) -> dict:
    """Serve the NOA on the innovator: opens the 45-day s.6 window."""
    if not record.get("noa_required"):
        raise NoaError("no NOA service is required for allegation "
                       f"'{record.get('allegation')}'", rule="noa_not_required")
    if record["status"] != STATUS_DRAFT:
        raise NoaError(f"NOA already {record['status']}; only a draft "
                       "allegation can be served", rule="not_draft")
    served = _iso(served_date)
    window_end = hc_calendar._as_date(served) + timedelta(
        days=ACTION_WINDOW_DAYS)
    r = dict(record)
    r["status"] = STATUS_SERVED
    r["served_date"] = served
    r["action_window_end"] = window_end.isoformat()
    r["history"] = record["history"] + [{"event": "noa_served", "at": served}]
    return r


def commence_action(record: dict, action_date, court_file: str = "") -> dict:
    """The innovator commences a s.6 action: starts the 24-month stay."""
    if record["status"] != STATUS_SERVED:
        raise NoaError("a s.6 action requires a served NOA", rule="not_served")
    action = _iso(action_date)
    if action < record["served_date"]:
        raise NoaError("action_date precedes NOA service",
                       rule="action_before_service")
    if action > record["action_window_end"]:
        raise NoaError("the 45-day window to commence a s.6 action has "
                       "expired", rule="action_window_expired")
    r = dict(record)
    r["status"] = STATUS_ACTION
    r["action_date"] = action
    r["court_file"] = _s(court_file) or None
    r["stay_start"] = action
    r["stay_end"] = add_months(action, STAY_MONTHS).isoformat()
    r["history"] = record["history"] + [
        {"event": "s6_action_commenced", "at": action}]
    return r


def resolve(record: dict, resolved_date, outcome: str = "") -> dict:
    """End the stay early (judgment, discontinuance, settlement)."""
    if record["status"] != STATUS_ACTION:
        raise NoaError("only a commenced s.6 action can be resolved",
                       rule="no_action")
    resolved = _iso(resolved_date)
    r = dict(record)
    r["status"] = STATUS_RESOLVED
    r["resolved_at"] = resolved
    r["outcome"] = _s(outcome) or None
    r["history"] = record["history"] + [
        {"event": "action_resolved", "at": resolved}]
    return r


def _remaining(end, as_of: date):
    return max(0, (hc_calendar._as_date(end) - as_of).days) if end else None


def with_clocks(record: dict, as_of=None) -> dict:
    """Record + computed clocks: derived status, days remaining, as_of."""
    on = hc_calendar._as_date(as_of) if _s(as_of) else date.today()
    view = dict(record)
    status = record["status"]
    if status == STATUS_SERVED and on > hc_calendar._as_date(
            record["action_window_end"]):
        status = STATUS_CLEAR
    elif status == STATUS_ACTION:
        status = (STATUS_STAY_RUNNING
                  if on < hc_calendar._as_date(record["stay_end"])
                  else STATUS_RESOLVED)
    view["status"] = status
    view["as_of"] = on.isoformat()
    view["action_days_remaining"] = _remaining(record["action_window_end"], on)
    view["stay_days_remaining"] = _remaining(record["stay_end"], on)
    return view
