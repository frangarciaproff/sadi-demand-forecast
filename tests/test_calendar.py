import datetime as dt

from sadi_forecast.calendar_ar import day_kind


def test_holiday_wins_when_two_share_a_date() -> None:
    k = day_kind([dt.date(2026, 4, 2), dt.date(2025, 4, 17), dt.date(2025, 8, 15)])
    assert k[dt.date(2026, 4, 2)] == "holiday"  # Malvinas + Holy Thursday
    assert k[dt.date(2025, 4, 17)] == "non_working"  # Holy Thursday alone
    assert k[dt.date(2025, 8, 15)] == "bridge"
