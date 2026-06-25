#!/usr/bin/env python3
"""
ANDS Submission Portal — Health Canada deadline calendar engine (REQ-052).

Pure-stdlib, deterministic day-counting under Health Canada's calendar
conventions:

* Canadian **federal statutory holidays** (the ones the federal public service
  / Health Canada observes), computed per year so the table is not a
  hand-maintained list — fixed-date holidays plus the moveable ones derived from
  the Gregorian Easter (Good Friday, Easter Monday) and the nth-weekday rules
  (Victoria Day, Labour Day, Thanksgiving).
* **Calendar-day vs business-day** deadline bases, *specified per notice type*
  (a clarifax counts calendar days; an internal screening/processing target
  counts working days) so the basis is data, not a hardcoded constant.
* A deadline that lands on a weekend or statutory holiday is **rolled forward**
  to the next business day and the adjustment is **surfaced** (never silent):
  the result carries both the nominal and adjusted due date plus the reason.
* A **configured review timezone** is carried on every computation and the
  holiday table can be supplied/extended as reference data without code changes.

Everything is date-level and clock-injectable: callers pass an ISO start date
the same way ``rep.py`` / ``transmission.py`` inject ``now``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TIMEZONE = "America/Toronto"      # HC review timezone (Eastern)

CALENDAR = "calendar"
BUSINESS = "business"

# REQ-052: the day-counting basis *per notice type*. Sponsor-facing regulatory
# response deadlines run on calendar days; HC's internal processing/screening
# performance targets are quoted in working (business) days. Data, not code.
NOTICE_BASIS = {
    "clarifax": CALENDAR,
    "sdn": CALENDAR,
    "nod": CALENDAR,
    "non": CALENDAR,
    "screening_target": BUSINESS,
    "processing_target": BUSINESS,
}


# ---------------------------------------------------------------------------
# Holiday computation
# ---------------------------------------------------------------------------

def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (Anonymous/Meeus computus)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th ``weekday`` (Mon=0) of ``month`` in ``year``."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _victoria_day(year: int) -> date:
    """The Monday on or before May 24 (Monday preceding May 25)."""
    d = date(year, 5, 24)
    return d - timedelta(days=(d.weekday()))  # back up to Monday (weekday 0)


def statutory_holidays(year: int) -> dict:
    """Federal statutory holidays observed by Health Canada for ``year`` as an
    ``{ "YYYY-MM-DD": name }`` map (computed, not hand-listed)."""
    easter = easter_sunday(year)
    holidays = {
        date(year, 1, 1): "New Year's Day",
        easter - timedelta(days=2): "Good Friday",
        easter + timedelta(days=1): "Easter Monday",
        _victoria_day(year): "Victoria Day",
        date(year, 7, 1): "Canada Day",
        _nth_weekday(year, 9, 0, 1): "Labour Day",
        date(year, 9, 30): "National Day for Truth and Reconciliation",
        _nth_weekday(year, 10, 0, 2): "Thanksgiving Day",
        date(year, 11, 11): "Remembrance Day",
        date(year, 12, 25): "Christmas Day",
        date(year, 12, 26): "Boxing Day",
    }
    return {d.isoformat(): name for d, name in holidays.items()}


def holiday_table(start_year: int, end_year: int) -> dict:
    """Merge :func:`statutory_holidays` across an inclusive year range."""
    table: dict = {}
    for y in range(start_year, end_year + 1):
        table.update(statutory_holidays(y))
    return table


# Default reference window. Callers may pass their own ``holidays`` map (e.g.
# loaded reference data with provincial observances) to override/extend it
# without touching this module.
DEFAULT_HOLIDAYS = holiday_table(2023, 2031)


# ---------------------------------------------------------------------------
# Day arithmetic
# ---------------------------------------------------------------------------

def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    # Accept full ISO timestamps or bare dates.
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date() \
        if ("T" in s or " " in s) else date.fromisoformat(s[:10])


def is_weekend(d) -> bool:
    return _as_date(d).weekday() >= 5


def is_holiday(d, holidays: dict = None) -> bool:
    holidays = DEFAULT_HOLIDAYS if holidays is None else holidays
    return _as_date(d).isoformat() in holidays


def holiday_name(d, holidays: dict = None):
    holidays = DEFAULT_HOLIDAYS if holidays is None else holidays
    return holidays.get(_as_date(d).isoformat())


def is_business_day(d, holidays: dict = None) -> bool:
    return not is_weekend(d) and not is_holiday(d, holidays)


def next_business_day(d, holidays: dict = None) -> date:
    cur = _as_date(d)
    while not is_business_day(cur, holidays):
        cur += timedelta(days=1)
    return cur


def add_calendar_days(start, n: int) -> date:
    return _as_date(start) + timedelta(days=int(n))


def add_business_days(start, n: int, holidays: dict = None) -> date:
    """Advance ``n`` business days from ``start`` (the start day itself is not
    counted; the result always lands on a business day)."""
    cur = _as_date(start)
    remaining = int(n)
    while remaining > 0:
        cur += timedelta(days=1)
        if is_business_day(cur, holidays):
            remaining -= 1
    return cur


def roll_forward(d, holidays: dict = None):
    """Roll ``d`` forward to the next business day if it falls on a weekend or
    statutory holiday. Returns ``(adjusted_date, was_adjusted, reason)``."""
    original = _as_date(d)
    if is_business_day(original, holidays):
        return original, False, None
    if is_holiday(original, holidays):
        reason = "statutory holiday: %s" % holiday_name(original, holidays)
    else:
        reason = "weekend (%s)" % original.strftime("%A")
    return next_business_day(original, holidays), True, reason


# ---------------------------------------------------------------------------
# Deadline computation (the public entry point)
# ---------------------------------------------------------------------------

def basis_for(notice_type: str, override: str = None) -> str:
    if override in (CALENDAR, BUSINESS):
        return override
    return NOTICE_BASIS.get(str(notice_type or "").lower(), CALENDAR)


def compute_deadline(start, days: int, basis: str = None, notice_type: str = "",
                     holidays: dict = None, timezone: str = DEFAULT_TIMEZONE):
    """Compute a regulatory deadline under HC conventions.

    * ``calendar`` basis: nominal due = start + ``days`` calendar days, then
      rolled forward off any weekend/holiday with the adjustment surfaced.
    * ``business`` basis: due = start + ``days`` business days (inherently a
      business day; no silent roll needed).

    Returns a dict carrying the start, basis, configured timezone, nominal and
    adjusted due dates, the adjustment flag and a human reason.
    """
    holidays = DEFAULT_HOLIDAYS if holidays is None else holidays
    resolved_basis = basis_for(notice_type, basis)
    start_date = _as_date(start)
    days = int(days)

    if resolved_basis == BUSINESS:
        due = add_business_days(start_date, days, holidays)
        nominal = due
        adjusted, reason = False, None
    else:
        nominal = add_calendar_days(start_date, days)
        due, adjusted, reason = roll_forward(nominal, holidays)

    return {
        "start": start_date.isoformat(),
        "days": days,
        "basis": resolved_basis,
        "notice_type": notice_type or None,
        "timezone": timezone,
        "nominal_due": nominal.isoformat(),
        "adjusted_due": due.isoformat(),
        "adjusted": adjusted,
        "adjustment_reason": reason,
        "due": due.isoformat(),            # the effective due date
    }


def business_days_between(start, end, holidays: dict = None) -> int:
    """Count business days in the half-open interval (start, end]."""
    a, b = _as_date(start), _as_date(end)
    if b <= a:
        return 0
    count = 0
    cur = a
    while cur < b:
        cur += timedelta(days=1)
        if is_business_day(cur, holidays):
            count += 1
    return count
