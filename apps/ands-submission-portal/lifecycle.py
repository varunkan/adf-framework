#!/usr/bin/env python3
"""
ANDS Submission Portal — post-receipt DSTS lifecycle, deadline timers & the
statutory fee-credit entitlement (REQ-030 / REQ-031 / REQ-062).

Pure-stdlib, deterministic and clock-injectable (callers pass an ISO ``now``
date the way ``transmission.py`` / ``rep.py`` do). Layers on top of
``hc_calendar`` for all day-counting so weekends, Canadian statutory holidays
and calendar-vs-business bases are honoured (REQ-052).

* REQ-030 — the post-receipt **DSTS lifecycle state machine**:
  Processing (~10 days) -> Screening (45-day target, with SAL/SDN/SRL outcomes)
  -> Review (ANDS 180-day target) -> decision (NOC/NOD/NON). The NOD/NON
  *Inactive* window (Inactive-45 vs Inactive-90) is **derived from the
  submission/application type**, never hardcoded to 45.
* REQ-031 — **deadline timers with proactive reminders**: SDN 45 days, clarifax
  tiers in the 2-15 calendar-day range (default by performance-standard tier but
  adjustable per HC-agreed window), NOD 90 days (45 for DIN). Plus **clock-stop**
  logic that pauses the Review clock during sponsor response windows.
* REQ-062 — detect when Health Canada **misses an applicable service standard**
  (ANDS 100% on-time-to-first-decision; 90% for tracked NC/CTA) and surface +
  record the statutory **25% fee-credit** entitlement (SOR/2019-124).
"""

from __future__ import annotations

from datetime import timedelta

import hc_calendar

# ---------------------------------------------------------------------------
# REQ-030 — phases, screening outcomes, decisions, statuses
# ---------------------------------------------------------------------------

PHASE_PROCESSING = "Processing"
PHASE_SCREENING = "Screening"
PHASE_REVIEW = "Review"
PHASE_COMPLETE = "Complete"

PHASE_ORDER = (PHASE_PROCESSING, PHASE_SCREENING, PHASE_REVIEW, PHASE_COMPLETE)

# Screening outcomes (REQ-030).
OUTCOME_SAL = "SAL"   # Screening Acceptance Letter — proceeds to Review
OUTCOME_SDN = "SDN"   # Screening Deficiency Notice — Inactive, 45-day response
OUTCOME_SRL = "SRL"   # Screening Rejection Letter — submission rejected
SCREENING_OUTCOMES = {
    OUTCOME_SAL: "Screening Acceptance Letter",
    OUTCOME_SDN: "Screening Deficiency Notice",
    OUTCOME_SRL: "Screening Rejection Letter",
}

# Decisions (REQ-030).
DECISION_NOC = "NOC"  # Notice of Compliance — approved
DECISION_NOD = "NOD"  # Notice of Deficiency
DECISION_NON = "NON"  # Notice of Non-compliance
DECISIONS = {
    DECISION_NOC: "Notice of Compliance",
    DECISION_NOD: "Notice of Deficiency",
    DECISION_NON: "Notice of Non-compliance",
}

# Statuses.
STATUS_ACTIVE = "Active"
STATUS_INACTIVE_45 = "Inactive-45"
STATUS_INACTIVE_90 = "Inactive-90"
STATUS_SCREENING_REJECTED = "Screening-Rejected"
STATUS_APPROVED = "Approved"

# REQ-033 — withdrawal / refiling / reconsideration statuses. HC auto-interprets
# a lapsed SDN/NOD/NON response window as a withdrawal and uses the EXACT
# hyphenated acronyms NOD-W and NON-W; an explicit (voluntary) withdrawal that
# is not tied to a decision notice is simply "Withdrawn".
STATUS_WITHDRAWN = "Withdrawn"
STATUS_WITHDRAWN_NOD = "NOD-W"   # withdrawal auto-interpreted after an NOD lapse
STATUS_WITHDRAWN_NON = "NON-W"   # withdrawal auto-interpreted after an NON lapse
W_STATUSES = frozenset({STATUS_WITHDRAWN, STATUS_WITHDRAWN_NOD,
                        STATUS_WITHDRAWN_NON})

# REQ-033 — map the notice whose window lapsed to HC's hyphenated W status.
W_STATUS_BY_KIND = {
    DECISION_NOD: STATUS_WITHDRAWN_NOD,
    DECISION_NON: STATUS_WITHDRAWN_NON,
}

# REQ-033/050 — response-timer kinds whose lapse auto-interprets as withdrawal.
RESPONSE_TIMER_KINDS = frozenset({"SDN", "NOD", "NON", "clarifax"})

# REQ-050 — the quality HC assigns to a received deficiency response. An
# acceptable response resumes the clock; a deficient one advances the dossier to
# the withdrawal interpretation (HC treats a deficient response like a lapse); an
# unsolicited submission is data sent without an open request and is tagged (and
# carries a regulatory-risk advisory) rather than closing any window.
RESPONSE_ACCEPTABLE = "acceptable"
RESPONSE_DEFICIENT = "deficient"
RESPONSE_UNSOLICITED = "unsolicited"
RESPONSE_QUALITIES = frozenset(
    {RESPONSE_ACCEPTABLE, RESPONSE_DEFICIENT, RESPONSE_UNSOLICITED})

# Terminal statuses that can no longer be withdrawn.
TERMINAL_STATUSES = frozenset({STATUS_APPROVED, STATUS_SCREENING_REJECTED})

# Phase targets.
PROCESSING_TARGET_DAYS = 10        # ~10 working days
SCREENING_TARGET_DAYS = 45         # screening performance target

# ---------------------------------------------------------------------------
# REQ-030 / REQ-034 / REQ-062 — service standards by submission class
# ---------------------------------------------------------------------------

# Review service standard: target days to first decision + the on-time KPI.
# ANDS (Division 1 & 8) is held to HC's 100% on-time-to-first-decision
# commitment; 90% applies only to other tracked classes (Notifiable Changes,
# CTAs). Data, not hardcoded constants.
SERVICE_STANDARDS = {
    "ANDS":  {"review_target_days": 180, "on_time_pct": 100,
              "label": "Abbreviated New Drug Submission"},
    "SANDS": {"review_target_days": 180, "on_time_pct": 100,
              "label": "Supplement to an ANDS"},
    "NDS":   {"review_target_days": 300, "on_time_pct": 100,
              "label": "New Drug Submission"},
    "SNDS":  {"review_target_days": 300, "on_time_pct": 100,
              "label": "Supplement to an NDS"},
    "DIN":   {"review_target_days": 180, "on_time_pct": 100,
              "label": "DIN application"},
    "NC":    {"review_target_days": 90,  "on_time_pct": 90,
              "label": "Notifiable Change"},
    "CTA":   {"review_target_days": 30,  "on_time_pct": 90,
              "label": "Clinical Trial Application"},
}
DEFAULT_CLASS = "ANDS"

# REQ-030: the Inactive window is type-derived. DIN-class applications get
# Inactive-45; full ANDS/NDS submissions get Inactive-90.
INACTIVE_45_CLASSES = frozenset({"DIN"})

# REQ-031: default clarifax response window (calendar days) by performance-
# standard tier — overridable to the HC-agreed value per notice.
CLARIFAX_DEFAULTS = {
    "0-90": 5,         # under the 0-90 day standard, a 5-day window
    "180-300": 15,     # under the 180-300 day standard, a 15-day window
}
DEFAULT_CLARIFAX_TIER = "180-300"
CLARIFAX_MIN_DAYS = 2
CLARIFAX_MAX_DAYS = 15

# REQ-035/REQ-062 — the ANDS comparative-studies fee (FY2025-26 seed) used as
# the default "fee paid" when computing the 25% credit. SOR/2019-124.
ANDS_COMPARATIVE_STUDIES_FEE = 70750.0
FEE_CREDIT_RATE = 0.25

# REQ-031 — proactive reminder cadence as fractions of the response window.
REMINDER_FRACTIONS = (0.5, 0.8, 1.0)


class LifecycleError(Exception):
    """Raised for an illegal DSTS lifecycle transition."""


# ---------------------------------------------------------------------------
# Type-derivation helpers (REQ-030 / REQ-034 / REQ-062)
# ---------------------------------------------------------------------------

def submission_class(submission_type) -> str:
    return (str(submission_type or "").strip().upper() or DEFAULT_CLASS)


def service_standard(submission_type) -> dict:
    return SERVICE_STANDARDS.get(submission_class(submission_type),
                                 SERVICE_STANDARDS[DEFAULT_CLASS])


def review_target_days(submission_type) -> int:
    return service_standard(submission_type)["review_target_days"]


def inactive_window_days(submission_type) -> int:
    """REQ-030: 45 days for DIN-class applications, 90 days otherwise."""
    return 45 if submission_class(submission_type) in INACTIVE_45_CLASSES else 90


def inactive_status(submission_type) -> str:
    return (STATUS_INACTIVE_45 if inactive_window_days(submission_type) == 45
            else STATUS_INACTIVE_90)


def clarifax_default_days(tier) -> int:
    return CLARIFAX_DEFAULTS.get(str(tier or "").strip(),
                                 CLARIFAX_DEFAULTS[DEFAULT_CLARIFAX_TIER])


# ---------------------------------------------------------------------------
# REQ-031 — deadline timers
# ---------------------------------------------------------------------------

def _reminder_dates(start, due) -> list:
    """Proactive reminder dates as fractions of the window (REQ-031)."""
    s = hc_calendar._as_date(start)
    d = hc_calendar._as_date(due)
    total = (d - s).days
    out = []
    for frac in REMINDER_FRACTIONS:
        out.append((s + timedelta(days=int(round(total * frac)))).isoformat())
    return sorted(set(out))


def build_timer(kind: str, start, days: int, notice_type: str = "",
                basis: str = None, holidays: dict = None,
                label: str = "") -> dict:
    """Build a deadline timer with proactive reminders (REQ-031).

    Day-counting is delegated to ``hc_calendar`` so the basis (calendar vs
    business), weekends and statutory holidays are honoured and any weekend/
    holiday roll is surfaced (REQ-052).
    """
    deadline = hc_calendar.compute_deadline(
        start, days, basis=basis, notice_type=notice_type or kind,
        holidays=holidays)
    return {
        "kind": kind,
        "label": label or kind,
        "days": int(days),
        "notice_type": notice_type or kind,
        "start": deadline["start"],
        "basis": deadline["basis"],
        "nominal_due": deadline["nominal_due"],
        "due": deadline["due"],
        "adjusted": deadline["adjusted"],
        "adjustment_reason": deadline["adjustment_reason"],
        "reminders": _reminder_dates(deadline["start"], deadline["due"]),
        "status": "open",
        "responded_at": None,
    }


# ---------------------------------------------------------------------------
# REQ-030/031/062 — the DSTS lifecycle aggregate
# ---------------------------------------------------------------------------

class Lifecycle:
    """The post-receipt DSTS lifecycle for one dossier/submission.

    Tracks the phase/status state machine (REQ-030), the open deadline timers
    and Review clock-stop windows (REQ-031), and the missed-service-standard /
    25% fee-credit entitlement (REQ-062). Serialisable to/from a dict for
    sqlite storage. All dates are ISO; ``now`` is injected for determinism.
    """

    def __init__(self, dossier_id: str, submission_type: str = DEFAULT_CLASS,
                 core_id: str = "", fee_paid=None):
        self.dossier_id = str(dossier_id or "").strip()
        self.submission_type = submission_class(submission_type)
        self.core_id = str(core_id or "").strip()
        self.fee_paid = (float(fee_paid) if fee_paid not in (None, "")
                         else ANDS_COMPARATIVE_STUDIES_FEE)
        self.phase = None
        self.status = None
        self.started_at = None
        self.review_started_at = None
        self.screening_outcome = None
        self.decision = None
        self.decided_at = None
        self.timers = []         # active/closed deadline timers
        self.clock_stops = []    # Review clock-stop windows
        self.fee_credit = None   # REQ-062 entitlement, once triggered
        self.history = []        # immutable, time-ordered event trail
        # REQ-033 — withdrawal / refiling / reconsideration state.
        self.withdrawn = False
        self.withdrawal = None       # {reason, auto, w_status, at, notice}
        self.refilings = []          # refiled-without-prejudice records
        self.reconsideration = None  # {requested, at} once filed
        # REQ-050 — received deficiency-response records (acceptable / deficient
        # / unsolicited), including any late-filing override + rationale.
        self.responses = []
        # REQ-051 — monotonic per-notice id counter so concurrent clarifaxes
        # (and other response notices) are individually addressable.
        self._notice_seq = 0

    # -- serialization --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "dossier_id": self.dossier_id,
            "submission_type": self.submission_type,
            "core_id": self.core_id,
            "fee_paid": self.fee_paid,
            "phase": self.phase,
            "status": self.status,
            "started_at": self.started_at,
            "review_started_at": self.review_started_at,
            "screening_outcome": self.screening_outcome,
            "decision": self.decision,
            "decided_at": self.decided_at,
            "timers": self.timers,
            "clock_stops": self.clock_stops,
            "fee_credit": self.fee_credit,
            "history": self.history,
            "withdrawn": self.withdrawn,
            "withdrawal": self.withdrawal,
            "refilings": self.refilings,
            "reconsideration": self.reconsideration,
            "responses": self.responses,
            "notice_seq": self._notice_seq,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Lifecycle":
        lc = cls(data.get("dossier_id", ""), data.get("submission_type"),
                 data.get("core_id", ""), data.get("fee_paid"))
        lc.phase = data.get("phase")
        lc.status = data.get("status")
        lc.started_at = data.get("started_at")
        lc.review_started_at = data.get("review_started_at")
        lc.screening_outcome = data.get("screening_outcome")
        lc.decision = data.get("decision")
        lc.decided_at = data.get("decided_at")
        lc.timers = list(data.get("timers") or [])
        lc.clock_stops = list(data.get("clock_stops") or [])
        lc.fee_credit = data.get("fee_credit")
        lc.history = list(data.get("history") or [])
        lc.withdrawn = bool(data.get("withdrawn"))
        lc.withdrawal = data.get("withdrawal")
        lc.refilings = list(data.get("refilings") or [])
        lc.reconsideration = data.get("reconsideration")
        lc.responses = list(data.get("responses") or [])
        lc._notice_seq = int(data.get("notice_seq") or 0)
        return lc

    # -- helpers --------------------------------------------------------
    def _log(self, event: str, detail: str, now=None) -> None:
        self.history.append({"event": event, "detail": detail,
                             "at": str(now) if now is not None else None})

    def _add_timer(self, timer: dict) -> dict:
        self.timers.append(timer)
        return timer

    def _next_notice_id(self, kind: str) -> str:
        """REQ-051: a stable, unique id for a response notice so concurrent
        clarifaxes (and SDN/NOD/NON timers) are individually addressable."""
        self._notice_seq += 1
        return f"{str(kind or 'notice').lower()}-{self._notice_seq}"

    def _open_clock_stop(self, reason: str, now, notice_id: str = "") -> None:
        """REQ-031/051: pause the Review clock for a sponsor response window.

        ``notice_id`` ties the window to the response timer that opened it so a
        per-notice resume (REQ-051) can close exactly the right one when several
        overlap."""
        self.clock_stops.append({"reason": reason,
                                 "notice_id": str(notice_id or ""),
                                 "started_at": str(now) if now else None,
                                 "ended_at": None})

    def _close_open_clock_stop(self, now, notice_id: str = "") -> bool:
        """Close the most recently opened still-open clock-stop, or — when a
        ``notice_id`` is given — the specific window opened by that notice."""
        for cs in reversed(self.clock_stops):
            if cs.get("ended_at") is not None:
                continue
            if notice_id and cs.get("notice_id") != notice_id:
                continue
            cs["ended_at"] = str(now) if now else None
            return True
        return False

    def open_timers(self) -> list:
        return [t for t in self.timers if t.get("status") == "open"]

    # -- REQ-030: phase transitions -------------------------------------
    def start(self, now=None) -> dict:
        """Begin tracking on receipt by HC — status starts at Processing."""
        if self.phase is not None:
            raise LifecycleError("lifecycle already started")
        self.phase = PHASE_PROCESSING
        self.status = STATUS_ACTIVE
        self.started_at = str(now) if now else None
        self._add_timer(build_timer(
            "processing_target", now, PROCESSING_TARGET_DAYS,
            notice_type="processing_target",
            label="Processing target (~10 working days)"))
        self._log("started", "received by Health Canada — Processing begins", now)
        return self.status

    def to_screening(self, now=None) -> dict:
        if self.phase != PHASE_PROCESSING:
            raise LifecycleError(
                f"cannot enter Screening from phase {self.phase!r}")
        self.phase = PHASE_SCREENING
        self._add_timer(build_timer(
            "screening_target", now, SCREENING_TARGET_DAYS,
            notice_type="screening_target",
            label="Screening target (45 days)"))
        self._log("screening", "advanced to Screening (45-day target)", now)
        return self.status

    def record_screening_outcome(self, outcome: str, now=None) -> dict:
        """REQ-030: SAL -> Review; SDN -> Inactive-45 + 45-day timer; SRL ->
        Screening-Rejected."""
        outcome = str(outcome or "").strip().upper()
        if self.phase != PHASE_SCREENING:
            raise LifecycleError("screening outcome requires the Screening phase")
        if outcome not in SCREENING_OUTCOMES:
            raise LifecycleError(
                f"screening outcome must be one of {sorted(SCREENING_OUTCOMES)}")
        self.screening_outcome = outcome
        if outcome == OUTCOME_SAL:
            self._log("SAL", "Screening Acceptance Letter — proceed to Review",
                      now)
            return self.to_review(now)
        if outcome == OUTCOME_SDN:
            # An SDN is a screening deficiency: a 45-day sponsor response timer
            # and an Inactive-45 status (REQ-030/031).
            self.status = STATUS_INACTIVE_45
            self._add_timer(build_timer(
                "SDN", now, 45, notice_type="sdn",
                label="Screening Deficiency Notice response (45 days)"))
            self._open_clock_stop("SDN response window", now)
            self._log("SDN", "Screening Deficiency Notice — Inactive-45, "
                             "45-day response timer", now)
            return self.status
        # SRL — screening rejection, terminal.
        self.status = STATUS_SCREENING_REJECTED
        self.phase = PHASE_COMPLETE
        self._log("SRL", "Screening Rejection Letter — submission rejected", now)
        return self.status

    def to_review(self, now=None) -> dict:
        if self.phase not in (PHASE_SCREENING,):
            raise LifecycleError(
                f"cannot enter Review from phase {self.phase!r}")
        self.phase = PHASE_REVIEW
        self.status = STATUS_ACTIVE
        self.review_started_at = str(now) if now else None
        self._add_timer(build_timer(
            "review_target", now, review_target_days(self.submission_type),
            notice_type="review_target",
            label=f"Review target ({review_target_days(self.submission_type)} "
                  f"days, {self.submission_type})"))
        self._log("review", "advanced to Review "
                            f"({review_target_days(self.submission_type)}-day "
                            "target)", now)
        return self.status

    # -- REQ-031: review deficiencies + clock-stop ----------------------
    def issue_clarifax(self, tier: str = DEFAULT_CLARIFAX_TIER,
                       response_days=None, now=None) -> dict:
        """Issue a clarifax (clarification request) during Review.

        The default response window is set by the performance-standard ``tier``
        (5 days under 0-90; 15 days under 180-300) but is **overridable** to the
        HC-agreed value via ``response_days``. The Review clock is paused for the
        sponsor response window (REQ-031 clock-stop)."""
        if self.phase != PHASE_REVIEW:
            raise LifecycleError("a clarifax can only be issued during Review")
        if response_days in (None, ""):
            days = clarifax_default_days(tier)
            overridden = False
        else:
            days = int(response_days)
            overridden = True
        timer = build_timer(
            "clarifax", now, days, notice_type="clarifax",
            label=f"Clarifax response ({days} days)")
        timer["tier"] = tier
        timer["overridden"] = overridden
        if days < CLARIFAX_MIN_DAYS or days > CLARIFAX_MAX_DAYS:
            timer["outside_nominal_range"] = True
            timer["range_note"] = (f"window {days}d is outside the nominal "
                                   f"{CLARIFAX_MIN_DAYS}-{CLARIFAX_MAX_DAYS}-day "
                                   "clarifax range (HC-agreed override)")
        self._add_timer(timer)
        self._open_clock_stop("clarifax response window", now)
        self._log("clarifax", f"clarifax issued — {days}-day window "
                             f"(tier {tier}{', overridden' if overridden else ''})",
                  now)
        return timer

    def resume_clock(self, now=None) -> bool:
        """REQ-031: the sponsor responded — close the open clock-stop window and
        resume the Review clock. Any open response timer is marked responded."""
        closed = self._close_open_clock_stop(now)
        if not closed:
            raise LifecycleError("no open clock-stop window to resume")
        for t in self.timers:
            if t.get("status") == "open" and t.get("kind") in (
                    "clarifax", "SDN", "NOD", "NON"):
                t["status"] = "responded"
                t["responded_at"] = str(now) if now else None
        if self.status in (STATUS_INACTIVE_45, STATUS_INACTIVE_90):
            self.status = STATUS_ACTIVE
        self._log("resume", "sponsor responded — Review clock resumes", now)
        return True

    # -- REQ-030: decisions ---------------------------------------------
    def record_decision(self, decision: str, now=None) -> dict:
        """Record a first decision (REQ-030). NOC approves; NOD/NON set the
        type-derived Inactive window + response timer + clock-stop."""
        decision = str(decision or "").strip().upper()
        if decision not in DECISIONS:
            raise LifecycleError(
                f"decision must be one of {sorted(DECISIONS)}")
        if self.phase not in (PHASE_REVIEW,):
            raise LifecycleError("a decision requires the Review phase")
        self.decision = decision
        self.decided_at = str(now) if now else None
        if decision == DECISION_NOC:
            self.phase = PHASE_COMPLETE
            self.status = STATUS_APPROVED
            self._log("NOC", "Notice of Compliance — approved", now)
            return self.status
        # NOD / NON — Inactive window derived from submission type (REQ-030),
        # with a response timer + clock-stop (REQ-031). NOD is 90 days (45 for
        # DIN); NON mirrors the type-derived Inactive window.
        days = inactive_window_days(self.submission_type)
        self.status = inactive_status(self.submission_type)
        timer = build_timer(
            decision, now, days, notice_type=decision.lower(),
            label=f"{DECISIONS[decision]} response ({days} days)")
        self._add_timer(timer)
        self._open_clock_stop(f"{decision} response window", now)
        self._log(decision, f"{DECISIONS[decision]} — {self.status}, "
                           f"{days}-day response timer", now)
        return self.status

    # -- REQ-033: withdrawal / refiling / reconsideration ---------------
    def withdraw(self, now=None, reason: str = "", auto: bool = False,
                 w_status: str = None, notice: str = "") -> str:
        """Withdraw the submission (REQ-033).

        Explicit (voluntary) withdrawals land in ``Withdrawn``; an
        auto-interpreted withdrawal after a lapsed decision notice carries HC's
        exact hyphenated acronym (NOD-W / NON-W). A submission that has already
        reached a terminal state (Approved / Screening-Rejected) or is already
        withdrawn cannot be withdrawn again."""
        if self.withdrawn:
            raise LifecycleError("submission is already withdrawn")
        if self.status in TERMINAL_STATUSES:
            raise LifecycleError(
                f"cannot withdraw a {self.status} submission")
        status = w_status or STATUS_WITHDRAWN
        if status not in W_STATUSES:
            raise LifecycleError(f"invalid withdrawal status {status!r}")
        self.withdrawn = True
        self.status = status
        self.phase = PHASE_COMPLETE
        # A withdrawal closes any open response window/clock-stop.
        self._close_open_clock_stop(now)
        for t in self.open_timers():
            t["status"] = "closed-withdrawn"
        self.withdrawal = {
            "reason": str(reason or "").strip()
            or ("response window lapsed" if auto else "voluntary withdrawal"),
            "auto": bool(auto),
            "w_status": status,
            "notice": str(notice or "").strip(),
            "at": str(now) if now is not None else None,
        }
        self._log("withdrawal",
                  f"{'auto-interpreted' if auto else 'explicit'} withdrawal "
                  f"-> {status}", now)
        return self.status

    def check_deadlines(self, now=None) -> list:
        """REQ-033/050: detect lapsed response windows and auto-interpret.

        Any still-open SDN/NOD/NON/clarifax timer whose ``due`` date is strictly
        before ``now`` is marked lapsed. HC auto-interprets a lapsed response
        window as a withdrawal, using the hyphenated W acronym of the most severe
        lapsed notice (NON-W > NOD-W; an SDN/clarifax-only lapse is ``Withdrawn``).
        Returns the list of lapsed timers (empty if none). Idempotent once
        withdrawn."""
        if now is None or self.withdrawn:
            return []
        now_d = hc_calendar._as_date(now)
        lapsed = []
        for t in self.timers:
            if t.get("status") != "open":
                continue
            if t.get("kind") not in RESPONSE_TIMER_KINDS:
                continue
            if now_d > hc_calendar._as_date(t["due"]):
                t["status"] = "lapsed"
                t["lapsed_at"] = str(now)
                lapsed.append(t)
        if not lapsed:
            return []
        kinds = {t["kind"] for t in lapsed}
        if DECISION_NON in kinds:
            w_status, notice = STATUS_WITHDRAWN_NON, DECISION_NON
        elif DECISION_NOD in kinds:
            w_status, notice = STATUS_WITHDRAWN_NOD, DECISION_NOD
        else:
            w_status, notice = STATUS_WITHDRAWN, sorted(kinds)[0]
        self.withdraw(now=now, auto=True, w_status=w_status, notice=notice,
                      reason=f"{notice} response window lapsed without a response")
        return lapsed

    def refile(self, now=None) -> dict:
        """REQ-033: refiling without prejudice.

        A withdrawn submission may be refiled; this never blocks the dossier (a
        new submission/sequence can proceed). Records the refiling and returns a
        descriptor for the new filing."""
        if not self.withdrawn:
            raise LifecycleError(
                "only a withdrawn submission can be refiled")
        record = {
            "without_prejudice": True,
            "prior_status": self.status,
            "at": str(now) if now is not None else None,
        }
        self.refilings.append(record)
        self._log("refile", "refiled without prejudice "
                            f"(prior status {self.status})", now)
        return {"dossier_id": self.dossier_id, "refiled": True,
                "blocked": False, **record}

    def request_reconsideration(self, now=None) -> dict:
        """REQ-033: request-for-reconsideration path.

        Available for an NON or an auto-interpreted NON-W (HC's reconsideration
        process applies to a Notice of Non-compliance outcome)."""
        if self.decision != DECISION_NON and self.status != STATUS_WITHDRAWN_NON:
            raise LifecycleError(
                "reconsideration applies to an NON / NON-W outcome only")
        self.reconsideration = {"requested": True,
                                "at": str(now) if now is not None else None}
        self._log("reconsideration",
                  "request for reconsideration filed", now)
        return self.reconsideration

    # -- REQ-062: missed service standard -> 25% fee credit -------------
    def review_days_elapsed(self, now=None) -> int:
        """Calendar days in Review, excluding clock-stopped windows (REQ-031).

        The Review clock is paused during every sponsor response window, so the
        elapsed count against the service standard reflects HC's review time
        only — not the time the ball was in the sponsor's court.
        """
        if not self.review_started_at:
            return 0
        end = self.decided_at or now
        if end is None:
            return 0
        start_d = hc_calendar._as_date(self.review_started_at)
        end_d = hc_calendar._as_date(end)
        gross = (end_d - start_d).days
        stopped = 0
        for cs in self.clock_stops:
            if not cs.get("started_at"):
                continue
            cs_start = hc_calendar._as_date(cs["started_at"])
            cs_end = hc_calendar._as_date(cs["ended_at"]) if cs.get("ended_at") \
                else end_d
            # Clip the stop window to the [review_start, end] interval.
            lo = max(cs_start, start_d)
            hi = min(cs_end, end_d)
            if hi > lo:
                stopped += (hi - lo).days
        return max(0, gross - stopped)

    def check_service_standard(self, now=None) -> dict:
        """REQ-062: evaluate days-elapsed-vs-target and, when HC has missed the
        applicable service standard, surface + record the 25% fee-credit
        entitlement (SOR/2019-124)."""
        std = service_standard(self.submission_type)
        target = std["review_target_days"]
        elapsed = self.review_days_elapsed(now)
        # HC "misses" the standard when the first decision has not been reached
        # (NOC) within the target review time. A late NOC also counts.
        decided_on_time = (self.decision == DECISION_NOC
                           and elapsed <= target)
        missed = (elapsed > target) and not (
            self.decision == DECISION_NOC and elapsed <= target)
        result = {
            "dossier_id": self.dossier_id,
            "submission_type": self.submission_type,
            "submission_class_label": std["label"],
            "review_target_days": target,
            "on_time_standard_pct": std["on_time_pct"],
            "days_elapsed": elapsed,
            "days_over": max(0, elapsed - target),
            "on_time": decided_on_time or (elapsed <= target),
            "missed_standard": bool(missed),
            "fee_paid": self.fee_paid,
            "fee_credit": None,
        }
        if missed:
            credit = round(self.fee_paid * FEE_CREDIT_RATE, 2)
            entitlement = {
                "rate": FEE_CREDIT_RATE,
                "fee_paid": self.fee_paid,
                "amount": credit,
                "authority": "SOR/2019-124",
                "reason": (f"Review exceeded the {target}-day service standard "
                          f"for an {self.submission_type} by {elapsed - target} "
                          "day(s); a 25% fee credit applies."),
                "triggered_at": str(now) if now else None,
            }
            self.fee_credit = entitlement
            result["fee_credit"] = entitlement
            self._log("fee_credit", entitlement["reason"], now)
        elif self.fee_credit:
            # Already triggered earlier — keep surfacing it.
            result["fee_credit"] = self.fee_credit
        return result

    # -- snapshot -------------------------------------------------------
    def status_view(self, now=None) -> dict:
        snap = self.to_dict()
        snap["open_timers"] = self.open_timers()
        snap["review_days_elapsed"] = self.review_days_elapsed(now)
        snap["service_standard"] = service_standard(self.submission_type)
        snap["inactive_window_days"] = inactive_window_days(self.submission_type)
        snap["withdrawn"] = self.withdrawn
        return snap
