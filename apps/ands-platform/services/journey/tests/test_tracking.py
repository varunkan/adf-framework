"""Tests for the post-filing HC review tracker (pure, clock-injected)."""

from __future__ import annotations

from app import tracking


# -- windows / constants ------------------------------------------------------
def test_windows_are_named_constants_with_hc_numbers():
    assert tracking.SDN_DAYS == 45
    assert tracking.CLARIFAX_DAYS == 15
    assert tracking.NOD_DAYS == 90
    assert tracking.NON_DAYS == 90
    assert tracking.SCREENING_TARGET_DAYS == 45
    assert tracking.REVIEW_TARGET_DAYS_ANDS == 180


# -- SDN 45-day window + days_remaining math ---------------------------------
def test_sdn_timer_45_day_window_and_due_date():
    notices = [{"type": "SDN", "date": "2026-01-01"}]
    timers = tracking.timers(notices, as_of="2026-01-01")
    assert len(timers) == 1
    t = timers[0]
    assert t["window_days"] == 45
    # 45 calendar days after Jan 1 -> Feb 15
    assert t["due_date"] == "2026-02-15"
    assert t["days_remaining"] == 45
    assert t["overdue"] is False
    assert t["paused"] is False


def test_sdn_days_remaining_counts_down_with_as_of():
    notices = [{"type": "SDN", "date": "2026-01-01"}]
    # 10 days elapsed -> 35 remaining
    t = tracking.timers(notices, as_of="2026-01-11")[0]
    assert t["days_remaining"] == 35
    assert t["overdue"] is False


def test_sdn_overdue_when_as_of_past_due():
    notices = [{"type": "SDN", "date": "2026-01-01"}]
    t = tracking.timers(notices, as_of="2026-03-01")[0]  # well past Feb 15
    assert t["days_remaining"] < 0
    assert t["overdue"] is True


def test_sdn_carries_srl_warning_in_guidance():
    notices = [{"type": "SDN", "date": "2026-01-01"}]
    t = tracking.timers(notices, as_of="2026-01-01")[0]
    assert "SRL" in t["guidance"] or "Screening Rejection" in t["guidance"]


# -- SAL moves phase to review with no timer ---------------------------------
def test_sal_moves_phase_to_review_and_no_timer():
    notices = [{"type": "SDN", "date": "2026-01-01"},
               {"type": "SAL", "date": "2026-02-01"}]
    ph = tracking.phase(notices)
    assert ph["phase"] == "review"
    assert ph["target_days"] == tracking.REVIEW_TARGET_DAYS_ANDS
    # SAL clears the screening timer; nothing outstanding
    assert tracking.timers(notices, as_of="2026-02-02") == []


# -- clarifax 15 days ---------------------------------------------------------
def test_clarifax_15_day_window():
    notices = [{"type": "SAL", "date": "2026-02-01"},
               {"type": "clarifax", "date": "2026-03-01"}]
    t = next(x for x in tracking.timers(notices, as_of="2026-03-01")
             if x["notice"]["type"] == "clarifax")
    assert t["window_days"] == 15
    assert t["due_date"] == "2026-03-16"
    assert t["days_remaining"] == 15


# -- NOD 90 days + phase review-stopped --------------------------------------
def test_nod_90_day_window_and_phase_stopped():
    notices = [{"type": "NOD", "date": "2026-04-01"}]
    t = tracking.timers(notices, as_of="2026-04-01")[0]
    assert t["window_days"] == 90
    assert t["due_date"] == "2026-06-30"
    assert t["days_remaining"] == 90
    ph = tracking.phase(notices)
    assert "stop" in ph["phase"]  # review-stopped


# -- NON window exposed -------------------------------------------------------
def test_non_default_90_day_window_and_decision_phase():
    notices = [{"type": "NON", "date": "2026-05-01"}]
    t = tracking.timers(notices, as_of="2026-05-01")[0]
    assert t["window_days"] == 90
    assert tracking.phase(notices)["phase"] == "decision"


# -- NOC terminal decision, no timer -----------------------------------------
def test_noc_is_terminal_decision_no_timer():
    notices = [{"type": "SAL", "date": "2026-02-01"},
               {"type": "NOC", "date": "2026-09-01"}]
    ph = tracking.phase(notices)
    assert ph["phase"] == "decision"
    assert tracking.timers(notices, as_of="2026-09-02") == []


# -- pause-the-clock suppresses overdue --------------------------------------
def test_paused_clarifax_never_overdue():
    notices = [{"type": "SAL", "date": "2026-02-01"},
               {"type": "clarifax", "date": "2026-03-01"}]
    # as_of well past the 15-day due date, but paused
    t = next(x for x in tracking.timers(notices, as_of="2026-05-01",
                                        paused={"clarifax"})
             if x["notice"]["type"] == "clarifax")
    assert t["paused"] is True
    assert t["overdue"] is False


# -- next_deadline picks the soonest non-paused ------------------------------
def test_summarize_next_deadline_picks_soonest():
    notices = [{"type": "SDN", "date": "2026-01-01"}]
    s = tracking.summarize(notices, as_of="2026-01-01")
    assert s["next_deadline"] == "2026-02-15"
    assert s["phase"]["phase"] == "screening"


def test_summarize_next_deadline_none_when_all_paused():
    notices = [{"type": "SAL", "date": "2026-02-01"},
               {"type": "clarifax", "date": "2026-03-01"}]
    s = tracking.summarize(notices, as_of="2026-03-01", paused={"clarifax"})
    assert s["next_deadline"] is None


# -- SRL advisory appears for an outstanding SDN -----------------------------
def test_summarize_srl_advisory_for_outstanding_sdn():
    notices = [{"type": "SDN", "date": "2026-01-01"}]
    s = tracking.summarize(notices, as_of="2026-01-10")
    rules = {a["rule"] for a in s["advisories"]}
    assert "srl_risk" in rules
    # the HC-time-only / real-time-is-longer note is always present
    assert "hc_time_only" in rules


def test_summarize_hc_time_note_always_present():
    notices = [{"type": "SAL", "date": "2026-02-01"}]
    s = tracking.summarize(notices, as_of="2026-02-02")
    rules = {a["rule"] for a in s["advisories"]}
    assert "hc_time_only" in rules
    # no SDN outstanding -> no SRL warning
    assert "srl_risk" not in rules


# -- empty / processing edge case --------------------------------------------
def test_empty_notices_is_processing_phase_no_timers():
    assert tracking.phase([])["phase"] == "processing"
    assert tracking.timers([], as_of="2026-01-01") == []
    s = tracking.summarize([], as_of="2026-01-01")
    assert s["next_deadline"] is None
    assert s["timers"] == []
