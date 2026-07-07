"""Health Canada deadline calendar — pure stdlib (ported verbatim, REQ-052).

Computed federal statutory holidays (fixed + Easter-derived + nth-weekday),
calendar-vs-business-day bases per notice type, and weekend/holiday roll-forward
with the adjustment surfaced.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

DEFAULT_TIMEZONE = "America/Toronto"
CALENDAR = "calendar"
BUSINESS = "business"

NOTICE_BASIS = {
    "clarifax": CALENDAR, "sdn": CALENDAR, "nod": CALENDAR, "non": CALENDAR,
    "screening_target": CALENDAR, "processing_target": CALENDAR,
}


def easter_sunday(year: int) -> date:
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
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _victoria_day(year: int) -> date:
    d = date(year, 5, 24)
    return d - timedelta(days=(d.weekday()))


def statutory_holidays(year: int) -> dict:
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
    table: dict = {}
    for y in range(start_year, end_year + 1):
        table.update(statutory_holidays(y))
    return table


DEFAULT_HOLIDAYS = holiday_table(2023, 2031)


def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
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
    cur = _as_date(start)
    remaining = int(n)
    while remaining > 0:
        cur += timedelta(days=1)
        if is_business_day(cur, holidays):
            remaining -= 1
    return cur


def roll_forward(d, holidays: dict = None):
    original = _as_date(d)
    if is_business_day(original, holidays):
        return original, False, None
    if is_holiday(original, holidays):
        reason = "statutory holiday: %s" % holiday_name(original, holidays)
    else:
        reason = "weekend (%s)" % original.strftime("%A")
    return next_business_day(original, holidays), True, reason


def basis_for(notice_type: str, override: str = None) -> str:
    if override in (CALENDAR, BUSINESS):
        return override
    return NOTICE_BASIS.get(str(notice_type or "").lower(), CALENDAR)


def compute_deadline(start, days: int, basis: str = None, notice_type: str = "",
                     holidays: dict = None, timezone: str = DEFAULT_TIMEZONE):
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
        "start": start_date.isoformat(), "days": days, "basis": resolved_basis,
        "notice_type": notice_type or None, "timezone": timezone,
        "nominal_due": nominal.isoformat(), "adjusted_due": due.isoformat(),
        "adjusted": adjusted, "adjustment_reason": reason,
        "due": due.isoformat()}


def business_days_between(start, end, holidays: dict = None) -> int:
    a, b = _as_date(start), _as_date(end)
    if b <= a:
        return 0
    count, cur = 0, a
    while cur < b:
        cur += timedelta(days=1)
        if is_business_day(cur, holidays):
            count += 1
    return count
