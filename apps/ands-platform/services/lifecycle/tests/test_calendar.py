"""Pure HC calendar — holidays, deadlines, weekend/holiday roll."""

from datetime import date

from app import hc_calendar


def test_easter_and_holidays_2025():
    assert hc_calendar.easter_sunday(2025) == date(2025, 4, 20)
    hols = hc_calendar.statutory_holidays(2025)
    assert hols["2025-07-01"] == "Canada Day"
    assert hols["2025-12-25"] == "Christmas Day"


def test_calendar_deadline_rolls_off_weekend():
    dl = hc_calendar.compute_deadline("2025-06-27", 1, notice_type="clarifax")
    assert dl["basis"] == "calendar"
    assert dl["nominal_due"] == "2025-06-28"   # Saturday
    assert dl["due"] == "2025-06-30"           # rolled to Monday
    assert dl["adjusted"] is True


def test_business_basis_lands_on_business_day():
    dl = hc_calendar.compute_deadline("2025-06-27", 1, basis="business")
    assert dl["basis"] == "business"
    assert dl["due"] == "2025-06-30"
    assert dl["adjusted"] is False


def test_business_days_between():
    # Fri 2025-06-27 -> Mon 2025-06-30 is one business day
    assert hc_calendar.business_days_between("2025-06-27", "2025-06-30") == 1
