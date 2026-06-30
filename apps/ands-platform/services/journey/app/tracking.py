"""Post-filing Health Canada review tracker — phases + deadline timers (pure).

Powers the guided "Track & respond" view (calm-the-timeline): once an ANDS is
transmitted, Health Canada works it through a fixed sequence of review phases and
issues notices the sponsor must answer inside hard calendar-day windows. This
module turns the logged notices into (a) the current review phase and (b) the
live response timers with days-remaining, so the front-end can show "you have N
days to respond" instead of a wall of regulatory acronyms.

Regulatory grounding (HC review of an ANDS, Management of Drug Submissions):
- Phases run processing -> screening (~45-day completeness target) -> review
  (~180-day science review for an ANDS) -> decision.
- Notices the sponsor logs and their response windows:
    * SDN  Screening Deficiency Notice  -> 45 calendar days; an incomplete or
           unsolicited-extra response risks a Screening Rejection Letter (SRL).
    * SAL  Screening Acceptance Letter  -> screening passed; phase -> review; no
           response timer.
    * clarifax  clarification during review -> 15 days (180-300-day review tier);
           clarify/re-analyse filed data only, do NOT add new data.
    * NOD  Notice of Deficiency  -> serious gaps, review stopped; 90 days; the
           response restarts a screening period.
    * NON  Notice of Non-compliance -> review finished short; 45 or 90 days by
           pathway (default 90; the window is exposed).
    * NOC  Notice of Compliance  -> APPROVED (a DIN issues); phase -> decision,
           terminal, no timer.
- "Pause the clock": a clarifax timer can be paused while the sponsor prepares;
  a paused timer is never overdue and its target/decision date pushes out.
- The 180-day target counts only HC's time and pauses while HC waits on the
  sponsor, so real elapsed time is longer — surfaced as a plain-language note,
  not as a hard date.

PURE: every "today" is the ``as_of`` argument ('YYYY-MM-DD'); the clock is never
read.
"""

from __future__ import annotations

from datetime import date, timedelta

# -- response windows / phase targets (HC numbers; never inline) -------------
SDN_DAYS = 45
CLARIFAX_DAYS = 15
NOD_DAYS = 90
NON_DAYS = 90
SCREENING_TARGET_DAYS = 45
REVIEW_TARGET_DAYS_ANDS = 180

# Actionable notices carry a response timer of this many calendar days.
_RESPONSE_WINDOWS = {
    "SDN": SDN_DAYS,
    "clarifax": CLARIFAX_DAYS,
    "NOD": NOD_DAYS,
    "NON": NON_DAYS,
}

# Notices that resolve / supersede an outstanding screening timer.
_SCREENING_NOTICES = {"SDN", "SAL"}

_PHASES = {
    "processing": {"label": "Logged with Health Canada",
                   "target_days": None,
                   "explanation": "Your submission is logged and waiting to "
                                  "enter the screening completeness check."},
    "screening": {"label": "Screening (completeness check)",
                  "target_days": SCREENING_TARGET_DAYS,
                  "explanation": "Health Canada is checking the submission is "
                                 "complete — a roughly 45-day target."},
    "review": {"label": "Science review",
               "target_days": REVIEW_TARGET_DAYS_ANDS,
               "explanation": "Health Canada is reviewing the science — a "
                              "~180-day target for an ANDS that counts only "
                              "HC's time."},
    "review-stopped": {"label": "Review stopped (deficiency)",
                       "target_days": REVIEW_TARGET_DAYS_ANDS,
                       "explanation": "The review is stopped pending your "
                                      "response; responding restarts a "
                                      "screening period."},
    "decision": {"label": "Decision issued",
                 "target_days": None,
                 "explanation": "Health Canada has reached a decision on this "
                                "submission."},
}


def _s(value) -> str:
    return str(value or "").strip()


def _d(value) -> date | None:
    try:
        return date.fromisoformat(_s(value))
    except ValueError:
        return None


def _add_days(start: str, days: int) -> str:
    base = _d(start)
    return (base + timedelta(days=days)).isoformat() if base else ""


def _ntype(notice) -> str:
    return _s((notice or {}).get("type"))


def _sorted(notices: list) -> list[dict]:
    """Logged notices in chronological order (stable on equal dates)."""
    items = [n for n in (notices or []) if isinstance(n, dict)]
    return sorted(items, key=lambda n: (_s(n.get("date")),))


# -- phase -------------------------------------------------------------------
def phase(notices: list) -> dict:
    """Derive the current review phase from the latest decisive notice.

    NOC/NON -> decision; NOD -> review-stopped; SAL -> review; an SDN (or any
    logged notice with none of the above) -> screening; nothing -> processing.
    """
    seen = {_ntype(n) for n in _sorted(notices)}
    if "NOC" in seen or "NON" in seen:
        key = "decision"
    elif "NOD" in seen:
        key = "review-stopped"
    elif "SAL" in seen:
        key = "review"
    elif seen:
        key = "screening"
    else:
        key = "processing"
    meta = _PHASES[key]
    return {"phase": key, "label": meta["label"],
            "target_days": meta["target_days"],
            "explanation": meta["explanation"]}


def _label_for(ntype: str, window: int) -> str:
    return {
        "SDN": f"Screening Deficiency Notice — respond within {window} days",
        "clarifax": f"Clarification request — respond within {window} days",
        "NOD": f"Notice of Deficiency — respond within {window} days",
        "NON": f"Notice of Non-compliance — respond within {window} days",
    }.get(ntype, f"Respond within {window} days")


def _guidance_for(ntype: str) -> str:
    return {
        "SDN": "Address every listed gap in one complete response. An "
               "incomplete response — or unsolicited extra data — risks a "
               "Screening Rejection Letter (SRL).",
        "clarifax": "Clarify or re-analyse the data already on file; do NOT "
                    "add new data. You may pause this timer while you prepare.",
        "NOD": "Serious gaps were found and the review is stopped. Your "
               "response restarts a screening period.",
        "NON": "The review finished but fell short. Respond within the window "
               "for your pathway (45 or 90 days; 90 shown by default).",
    }.get(ntype, "Respond within the stated window.")


def _is_outstanding(notice: dict, notices: list[dict]) -> bool:
    """Is this notice's response timer still live (not superseded)?"""
    ntype = _ntype(notice)
    if ntype not in _RESPONSE_WINDOWS:
        return False
    ndate = _s(notice.get("date"))
    # A later SAL accepts screening and clears the SDN's screening timer.
    if ntype == "SDN":
        for other in notices:
            if _ntype(other) == "SAL" and _s(other.get("date")) >= ndate:
                return False
    # A terminal decision (NOC/NON) closes any still-running review timer.
    for other in notices:
        if _ntype(other) in ("NOC",) and _s(other.get("date")) >= ndate:
            return False
    return True


# -- timers ------------------------------------------------------------------
def timers(notices: list, as_of: str, *, paused=()) -> list[dict]:
    """One active response timer per outstanding actionable notice.

    Each timer: {notice, due_date, days_remaining (int, may be negative),
    overdue, paused, window_days, label, guidance}. A paused timer reports
    paused=True and is never overdue (its date pushes out as the sponsor works).
    """
    paused = set(paused or ())
    ordered = _sorted(notices)
    today = _d(as_of)
    out: list[dict] = []
    for notice in ordered:
        ntype = _ntype(notice)
        if not _is_outstanding(notice, ordered):
            continue
        window = _RESPONSE_WINDOWS[ntype]
        due = _add_days(_s(notice.get("date")), window)
        due_d = _d(due)
        is_paused = ntype in paused
        if today is not None and due_d is not None:
            days_remaining = (due_d - today).days
        else:
            days_remaining = window
        overdue = (not is_paused) and days_remaining < 0
        out.append({
            "notice": dict(notice),
            "due_date": due,
            "days_remaining": days_remaining,
            "overdue": overdue,
            "paused": is_paused,
            "window_days": window,
            "label": _label_for(ntype, window),
            "guidance": _guidance_for(ntype),
        })
    return out


# -- the calm-the-timeline summary -------------------------------------------
_HC_TIME_NOTE = ("The ~180-day review target counts only Health Canada's time "
                 "and pauses whenever HC is waiting on you — so the real "
                 "calendar time to a decision is longer than 180 days.")


def summarize(notices: list, as_of: str, *, paused=()) -> dict:
    """The guided 'Track & respond' view: phase, live timers, next deadline and
    plain-language advisories (SRL warning + the HC-time-only note)."""
    ph = phase(notices)
    active = timers(notices, as_of, paused=paused)
    due_dates = [t["due_date"] for t in active
                 if not t["paused"] and t["due_date"]]
    next_deadline = min(due_dates) if due_dates else None

    advisories: list[dict] = []
    if any(t["notice"].get("type") == "SDN" for t in active):
        advisories.append({
            "rule": "srl_risk",
            "message": "An SDN is outstanding. Respond completely and on time — "
                       "an incomplete or unsolicited-extra response risks a "
                       "Screening Rejection Letter (SRL)."})
    advisories.append({"rule": "hc_time_only", "message": _HC_TIME_NOTE})

    return {"phase": ph, "timers": active,
            "next_deadline": next_deadline, "advisories": advisories}
