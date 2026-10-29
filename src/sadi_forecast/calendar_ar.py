"""Argentine calendar for the target day (known in advance, so usable at issue time).

Source: the `holidays` package (Argentina), which includes movable holidays and the
bridge days decreed "con fines turísticos". Categories:
    holiday      national holiday (feriado)
    bridge       day off decreed for tourism (feriado con fines turísticos)
    non_working  día no laborable (Holy Thursday): optional for employers
    eve          24 and 31 December (half working days, not legal holidays)
The category of a date is the first that applies, in this order.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import holidays
import pandas as pd

BRIDGE_NAME = "fines turísticos"
NON_WORKING_NAMES = ("Jueves Santo",)


def day_kind(dates: Iterable[dt.date]) -> pd.Series:
    """Holiday category per date ('' for ordinary days)."""
    dates = list(dates)
    years = sorted({d.year for d in dates})
    cal = holidays.country_holidays("AR", years=years)
    out = {}
    for d in dates:
        name = cal.get(d)
        if name is None:
            kind = "eve" if (d.month, d.day) in ((12, 24), (12, 31)) else ""
        elif BRIDGE_NAME in name:
            kind = "bridge"
        elif any(n in name for n in NON_WORKING_NAMES):
            kind = "non_working"
        else:
            kind = "holiday"
        out[d] = kind
    return pd.Series(out, name="day_kind")


def calendar_features(dates: Iterable[dt.date]) -> pd.DataFrame:
    """Day of week, holiday category, and the category of the previous and next day.

    Neighbour categories capture bridges into weekends and post-holiday Mondays.
    """
    dates = sorted(set(dates))
    if not dates:
        return pd.DataFrame()
    one = dt.timedelta(days=1)
    n = (dates[-1] - dates[0]).days + 3
    kind = day_kind(dates[0] - one + dt.timedelta(days=k) for k in range(n))
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "dow": d.weekday(),
                "day_kind": kind[d],
                "prev_day_kind": kind[d - one],
                "next_day_kind": kind[d + one],
                "off_day": d.weekday() == 6 or kind[d] in ("holiday", "bridge"),
            }
        )
    return pd.DataFrame(rows).set_index("date")
