"""DSTS lifecycle state machine — pure, functional (ported from monolith).

A lifecycle state is a plain dict (serialisable). Transition functions take a
state + an event and return a new state; ``now`` is injected for determinism.
Screening (SAL/SDN/SRL) → Review → decision (NOC/NOD/NON), with statutory-holiday
-aware deadline timers and the missed-service-standard 25% fee credit (REQ-062).
"""

from __future__ import annotations

from . import hc_calendar

# phases
PHASE_SCREENING = "Screening"
PHASE_REVIEW = "Review"
PHASE_COMPLETE = "Complete"

# screening outcomes
OUTCOME_SAL = "SAL"   # acceptance → Review
OUTCOME_SDN = "SDN"   # deficiency → Inactive
OUTCOME_SRL = "SRL"   # rejection → Complete
SCREENING_OUTCOMES = {OUTCOME_SAL: "Screening Acceptance Letter",
                      OUTCOME_SDN: "Screening Deficiency Notice",
                      OUTCOME_SRL: "Screening Rejection Letter"}

# decisions
DECISION_NOC = "NOC"
DECISION_NOD = "NOD"
DECISION_NON = "NON"
DECISIONS = {DECISION_NOC: "Notice of Compliance",
             DECISION_NOD: "Notice of Deficiency",
             DECISION_NON: "Notice of Non-compliance"}

# statuses
STATUS_ACTIVE = "Active"
STATUS_INACTIVE_45 = "Inactive-45"
STATUS_INACTIVE_90 = "Inactive-90"
STATUS_SCREENING_REJECTED = "Screening-Rejected"
STATUS_APPROVED = "Approved"
STATUS_WITHDRAWN = "Withdrawn"
TERMINAL_STATUSES = frozenset({STATUS_APPROVED, STATUS_SCREENING_REJECTED,
                               STATUS_WITHDRAWN})

SCREENING_TARGET_DAYS = 45
SDN_RESPONSE_DAYS = 45
ANDS_COMPARATIVE_STUDIES_FEE = 70750.0
FEE_CREDIT_RATE = 0.25

SERVICE_STANDARDS = {
    "ANDS": {"review_target_days": 180, "on_time_pct": 100,
             "label": "Abbreviated New Drug Submission"},
    "SANDS": {"review_target_days": 180, "on_time_pct": 100,
              "label": "Supplement to an ANDS"},
    "NDS": {"review_target_days": 300, "on_time_pct": 100,
            "label": "New Drug Submission"},
    "SNDS": {"review_target_days": 300, "on_time_pct": 100,
             "label": "Supplement to an NDS"},
    "DIN": {"review_target_days": 180, "on_time_pct": 100,
            "label": "DIN application"},
    "NC": {"review_target_days": 90, "on_time_pct": 90,
           "label": "Notifiable Change"},
    "CTA": {"review_target_days": 30, "on_time_pct": 90,
            "label": "Clinical Trial Application"},
}
DEFAULT_CLASS = "ANDS"
INACTIVE_45_CLASSES = frozenset({"DIN"})


class LifecycleError(Exception):
    """An illegal DSTS lifecycle transition."""


def submission_class(t) -> str:
    return str(t or "").strip().upper() or DEFAULT_CLASS


def service_standard(t) -> dict:
    return SERVICE_STANDARDS.get(submission_class(t),
                                 SERVICE_STANDARDS[DEFAULT_CLASS])


def review_target_days(t) -> int:
    return service_standard(t)["review_target_days"]


def inactive_window_days(t) -> int:
    return 45 if submission_class(t) in INACTIVE_45_CLASSES else 90


def inactive_status(t) -> str:
    return (STATUS_INACTIVE_45 if inactive_window_days(t) == 45
            else STATUS_INACTIVE_90)


def _timer(kind, start, days, notice_type) -> dict:
    dl = hc_calendar.compute_deadline(start, days, notice_type=notice_type)
    return {"kind": kind, "days": days, "start": dl["start"], "due": dl["due"],
            "basis": dl["basis"], "adjusted": dl["adjusted"], "status": "open"}


def start(dossier_id: str, submission_type: str, received_date: str,
          *, fee_paid=None) -> dict:
    """Begin the lifecycle at receipt: Screening phase + a 45-calendar-day
    screening target."""
    t = submission_class(submission_type)
    fee = float(fee_paid) if fee_paid not in (None, "") else \
        ANDS_COMPARATIVE_STUDIES_FEE
    screening = _timer("screening_target", received_date, SCREENING_TARGET_DAYS,
                       "screening_target")
    return {
        "dossier_id": str(dossier_id or "").strip(),
        "submission_type": t, "phase": PHASE_SCREENING, "status": STATUS_ACTIVE,
        "received_at": screening["start"], "review_started_at": None,
        "screening_outcome": None, "decision": None, "decided_at": None,
        "fee_paid": fee, "screening_due": screening["due"], "review_due": None,
        "fee_credit": None, "timers": [screening],
        "history": [{"event": "received", "at": screening["start"]}]}


def apply_screening(state: dict, outcome: str, on_date: str) -> dict:
    if state["phase"] != PHASE_SCREENING:
        raise LifecycleError("screening outcome only valid in the Screening phase")
    outcome = str(outcome or "").strip().upper()
    if outcome not in SCREENING_OUTCOMES:
        raise LifecycleError(f"unknown screening outcome: {outcome}")
    s = dict(state)
    s["timers"] = list(state["timers"])
    s["history"] = state["history"] + [
        {"event": f"screening:{outcome}", "at": on_date}]
    s["screening_outcome"] = outcome
    if outcome == OUTCOME_SAL:
        s["phase"] = PHASE_REVIEW
        s["status"] = STATUS_ACTIVE
        s["review_started_at"] = on_date
        review = _timer("review", on_date, review_target_days(s["submission_type"]),
                        "review")
        s["review_due"] = review["due"]
        s["timers"].append(review)
    elif outcome == OUTCOME_SDN:
        s["status"] = inactive_status(s["submission_type"])
        s["timers"].append(_timer("SDN", on_date, SDN_RESPONSE_DAYS, "sdn"))
    else:  # SRL
        s["phase"] = PHASE_COMPLETE
        s["status"] = STATUS_SCREENING_REJECTED
    return s


def apply_decision(state: dict, decision: str, on_date: str) -> dict:
    if state["phase"] != PHASE_REVIEW:
        raise LifecycleError("a decision is only valid in the Review phase")
    decision = str(decision or "").strip().upper()
    if decision not in DECISIONS:
        raise LifecycleError(f"unknown decision: {decision}")
    s = dict(state)
    s["timers"] = list(state["timers"])
    s["history"] = state["history"] + [
        {"event": f"decision:{decision}", "at": on_date}]
    s["decision"] = decision
    s["decided_at"] = on_date
    if decision == DECISION_NOC:
        s["phase"] = PHASE_COMPLETE
        s["status"] = STATUS_APPROVED
        s.update(_service_standard_result(s, on_date))
    else:  # NOD / NON
        s["status"] = inactive_status(s["submission_type"])
        s["timers"].append(_timer(
            decision, on_date, inactive_window_days(s["submission_type"]),
            decision.lower()))
    return s


def _service_standard_result(state: dict, decided_on: str) -> dict:
    """REQ-062: if HC decided after the review target, surface the 25% credit."""
    review_due = state.get("review_due")
    if not review_due:
        return {}
    on_time = hc_calendar._as_date(decided_on) <= hc_calendar._as_date(review_due)
    if on_time:
        return {"fee_credit": None}
    fee = float(state.get("fee_paid") or 0)
    credit = round(fee * FEE_CREDIT_RATE, 2) if fee > 0 else 0.0
    return {"fee_credit": {"missed_service_standard": True,
                           "review_due": review_due, "decided_at": decided_on,
                           "fee_paid": fee, "credit_rate": FEE_CREDIT_RATE,
                           "credit_amount": credit}}


def withdraw(state: dict, reason: str = "") -> dict:
    if state["status"] in TERMINAL_STATUSES:
        raise LifecycleError(f"cannot withdraw a {state['status']} submission")
    s = dict(state)
    s["status"] = STATUS_WITHDRAWN
    s["history"] = state["history"] + [
        {"event": "withdrawn", "reason": str(reason or "")}]
    return s
