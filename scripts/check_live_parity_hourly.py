"""Check that the forecast-time hourly inputs reproduce the backtest inputs (SPEC 11).

For a sample of days, the 24 shape-model rows built by production_hourly.design_for_day
(from live_features.features_for and the state's hourly weather) must equal the rows of
the backtest design (hourly.design_hourly over the whole table, as in
scripts/backtest_hourly.py). A difference means training and production would see
different inputs.

Usage (after build_features.py and seed_state.py):
    uv run python scripts/check_live_parity_hourly.py [--n 30]
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from sadi_forecast.daily import b1_daily
from sadi_forecast.features import valid_versions, weather_daily
from sadi_forecast.hourly import (
    FEATURES,
    design_hourly,
    hourly_temperature,
    programme_hourly,
    reference_shapes,
    version_shapes,
)
from sadi_forecast.live_features import GFS_COLUMN, features_for
from sadi_forecast.production_hourly import design_for_day, merge_hourly_weather
from sadi_forecast.weather import build_weather

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=30)
    args = p.parse_args(argv)
    table = pd.read_parquet(INTERIM / "features_daily.parquet")
    postop = _dates(pd.read_parquet(INTERIM / "d8_postop_versions.parquet"))
    supply = _dates(pd.read_parquet(INTERIM / "d7_supply_hourly.parquet"))
    programme = pd.read_parquet(INTERIM / "d6_programme_hourly.parquet")
    b1 = b1_daily(programme)
    weights = pd.read_csv(ROOT / "results" / "point_weights.csv", index_col="point")[
        "weight"
    ]
    raw = build_weather(ROOT / "data" / "raw" / "open_meteo", "gfs_prev")
    gfs_daily = weather_daily(raw, GFS_COLUMN)
    gfs_hourly = merge_hourly_weather(raw, pd.DataFrame())

    days_all = [d for d in table.index if d >= dt.date(2021, 4, 1)]
    shapes = version_shapes(valid_versions(postop, b1), programme_hourly(programme))
    s0, used = reference_shapes(shapes, days_all)
    temp = hourly_temperature(raw, GFS_COLUMN, weights)
    full = design_hourly(table, s0, temp, used, days_all)
    candidates = sorted(set(full["date"]))
    days = sorted(random.Random(0).sample(candidates, args.n))
    cols = [*FEATURES, "s0"]
    bad = 0
    for day in days:
        f = features_for(day, postop, supply, b1, gfs_daily, weights)
        live = design_for_day(f, postop, programme, gfs_hourly, weights, day)
        ref = full[full["date"] == day]
        for col in cols:
            a = live[col].to_numpy()
            b = ref[col].to_numpy()
            if a.dtype.kind in "fi" and b.dtype.kind in "fi":
                same = np.allclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True)
            else:
                same = bool((a.astype(str) == b.astype(str)).all())
            if not same:
                bad += 1
                print(f"{day} {col}: live {a[:3]} vs backtest {b[:3]}")
    print(f"{len(days)} days x 24 hours checked, {bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
