"""Daily national aggregation and version selection."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sadi_forecast.daily import (
    b1_daily,
    daily_national,
    first_and_last,
    national_by_version,
)

AREAS = [
    "BAS",
    "CENTRO",
    "COMAHUE",
    "CUYO",
    "GBA",
    "LITORAL",
    "NEA",
    "NOA",
    "PATAGONICA",
]


def _rows(
    doc: str, pub: str, day: dt.date, value: float, missing_area: str | None = None
) -> list[dict[str, object]]:
    return [
        {
            "doc_id": doc,
            "pub_date": dt.date.fromisoformat(pub),
            "pub_time": "12:00",
            "date": day,
            "area": a,
            "missing": a == missing_area,
            "energy_mwh": None if a == missing_area else value,
        }
        for a in AREAS
    ]


def test_incomplete_versions_are_nan_and_last_complete_wins() -> None:
    d1, d2 = dt.date(2019, 3, 4), dt.date(2019, 3, 5)
    rows = (
        _rows("A", "2019-03-14", d1, 10.0)
        + _rows("A", "2019-03-14", d2, 10.0, missing_area="NOA")
        + _rows("B", "2019-04-10", d1, 11.0)
        + _rows("B", "2019-04-10", d2, 12.0)
    )
    nat = national_by_version(pd.DataFrame(rows))
    assert nat["energy_mwh"].isna().sum() == 1
    days = first_and_last(nat)
    first = dict(zip(days["date"], days["energy_mwh_first"], strict=True))
    last = dict(zip(days["date"], days["energy_mwh_last"], strict=True))
    assert (first[d1], last[d1]) == (90.0, 99.0)
    assert first[d2] == 108.0  # first complete version is B
    series = daily_national(pd.DataFrame(rows))
    assert list(series.to_numpy()) == [99.0, 108.0]


def test_b1_daily_excludes_same_day_publications_and_prefers_format() -> None:
    d_txt, d_csv = dt.date(2024, 11, 12), dt.date(2024, 11, 13)
    rows = [
        # target, pub_date, pub_time, source, energy
        (d_txt, dt.date(2024, 11, 11), "21:30", "txt", 1.0),
        (d_txt, dt.date(2024, 11, 11), "21:30", "csv", 2.0),
        (d_txt, dt.date(2024, 11, 12), "08:00", "txt", 9.0),  # published on D
        (d_csv, dt.date(2024, 11, 12), "21:30", "txt", 3.0),
        (d_csv, dt.date(2024, 11, 12), "21:30", "csv", 4.0),
    ]
    prog = pd.DataFrame(
        rows, columns=["target_date", "pub_date", "pub_time", "source", "energy_mwh"]
    ).assign(doc_id="x")
    out = b1_daily(prog).set_index("target_date")["energy_mwh"].to_dict()
    assert out == {d_txt: 1.0, d_csv: 4.0}
