"""Calendar, point weights and lag availability (no network, synthetic data)."""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from sadi_forecast.calendar_ar import calendar_features
from sadi_forecast.features import issue_time, lag_table
from sadi_forecast.weights import DEMAND_CENTRES, nearest_point


def test_calendar_easter_2024() -> None:
    c = calendar_features(pd.date_range("2024-03-28", "2024-04-02").date)
    kinds = c["day_kind"].to_dict()
    assert kinds[dt.date(2024, 3, 28)] == "non_working"
    assert kinds[dt.date(2024, 3, 29)] == "holiday"
    assert kinds[dt.date(2024, 4, 1)] == "bridge"
    assert c["off_day"].to_dict()[dt.date(2024, 3, 31)]  # Sunday
    assert c["prev_day_kind"].to_dict()[dt.date(2024, 4, 2)] == "bridge"


def test_demand_centres_map_to_expected_points() -> None:
    assert nearest_point(DEMAND_CENTRES["rio negro"]) == "neuquen"
    assert nearest_point(DEMAND_CENTRES["entre rios"]) == "santa_fe"
    assert nearest_point(DEMAND_CENTRES["san luis"]) == "mendoza"


def test_lags_use_only_versions_published_before_issue() -> None:
    target = dt.date(2024, 5, 10)
    t = issue_time(target)  # 2024-05-09 10:00
    versions = pd.DataFrame(
        [
            # D-3, published D-2 evening: known at issue
            (dt.date(2024, 5, 7), t - dt.timedelta(hours=15), 100.0, "daily", True),
            # D-3 complement a month later: not known yet
            (dt.date(2024, 5, 7), t + dt.timedelta(days=30), 101.0, "complement", True),
            # D-4, invalid daily report, then a valid one
            (dt.date(2024, 5, 6), t - dt.timedelta(days=2), 999.0, "daily", False),
            # D-2 published after the issue time
            (dt.date(2024, 5, 8), t + dt.timedelta(hours=9), 98.0, "daily", True),
        ],
        columns=["date", "published_art", "value_mwh", "kind", "valid"],
    )
    lags = lag_table(versions, [target]).iloc[0]
    assert lags["lag_3"] == 100.0
    assert lags["lag_3_kind"] == "daily"
    assert math.isnan(lags["lag_4"])
    assert "lag_2" not in lags.index


def test_point_weights_sum_to_one_and_split_buenos_aires() -> None:
    from sadi_forecast.weights import point_weights

    day = dt.date(2020, 1, 1)
    provinces = pd.DataFrame(
        [
            {"date": day, "base": "2022-12", "province": p, "mwh": m}
            for p, m in (("buenos aires", 50.0), ("cordoba", 30.0), ("rio negro", 20.0))
        ]
        + [{"date": day, "base": "2022-12", "province": "total", "mwh": 100.0}]
    )
    d5 = pd.DataFrame(
        [
            {"date": day, "area": "GBA", "pub_date": day, "energy_mwh": 75.0},
            {"date": day, "area": "BAS", "pub_date": day, "energy_mwh": 25.0},
        ]
    ).assign(missing=False)
    w = point_weights(provinces, d5, day, day)["weight"]
    assert abs(w.sum() - 1) < 1e-12
    assert w["caba"] == 0.5 * 0.75
    assert w["mar_del_plata"] == w["bahia_blanca"] == 0.5 * 0.25 / 2
    assert w["neuquen"] == 0.2
