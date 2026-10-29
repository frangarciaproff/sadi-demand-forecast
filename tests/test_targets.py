"""Target construction and complement choice (SPEC 2.2)."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sadi_forecast.targets import definitive_daily, provisional_daily

D1, D2, D3 = dt.date(2020, 2, 14), dt.date(2020, 2, 15), dt.date(2020, 2, 16)


def _supply(day: dt.date, supply: float, exports: float) -> list[dict[str, object]]:
    return [
        {
            "base": "2021-12",
            "date": day,
            "hour": h,
            "supply_mwh": supply / 24,
            "export_mwh": exports / 24,
        }
        for h in range(1, 25)
    ]


def _postop() -> pd.DataFrame:
    rows = [
        (D1, "daily", "2020-02-15T20:00", 1000.0),
        (D1, "complement", "2020-03-10T12:00", 1001.0),
        (D2, "daily", "2020-02-17T20:00", 990.0),
        (D2, "complement", "2020-03-10T12:36", 998.0),
        (D2, "complement", "2020-03-10T12:37", 1030.0),  # later and wrong
        (D3, "complement", "2020-03-10T12:38", 1100.0),  # far from D7
    ]
    return pd.DataFrame(
        rows, columns=["date", "kind", "published", "supply_mwh"]
    ).assign(doc_id="x")


def test_complement_closest_to_d7_wins_and_far_ones_are_flagged() -> None:
    supply = pd.DataFrame(
        _supply(D1, 1001.0, 10.0) + _supply(D2, 998.2, 0.0) + _supply(D3, 1000.0, 0.0)
    )
    out = definitive_daily(_postop(), supply).set_index("date")
    assert out["target_mwh"].to_dict()[D1] == 991.0
    assert out["supply_mwh"].to_dict()[D2] == 998.0
    assert out["n_complements"].to_dict()[D2] == 2
    assert out["flag"].to_dict()[D3] == "complement_far_from_d7"
    assert pd.isna(out["target_mwh"].to_dict()[D3])


def test_without_d7_the_complement_closest_to_the_daily_report_is_provisional() -> None:
    out = definitive_daily(_postop(), pd.DataFrame(_supply(D1, 1001.0, 0.0)))
    row = out.set_index("date").loc[D2]
    assert row["supply_mwh"] == 998.0
    assert row["flag"] == "multiple_complements_provisional"


def test_provisional_subtracts_programmed_exports() -> None:
    b1 = pd.DataFrame(
        {"target_date": [D1], "exports_mwh": [25.0], "b1_total_mwh": [990.0]}
    )
    out = provisional_daily(_postop(), b1).set_index("date")
    assert out["provisional_mwh"].to_dict()[D1] == 975.0
