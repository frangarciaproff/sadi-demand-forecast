"""Check that the forecast-time feature path reproduces the training table.

For a sample of days, the model inputs built by live_features.features_for (only the
28-day window, GFS weather) must equal those of data/interim/features_daily.parquet.
A difference means training and production would see different inputs.

Usage (after build_features.py):
    uv run python scripts/check_live_parity.py [--n 40]
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
from sadi_forecast.features import weather_daily
from sadi_forecast.live_features import GFS_COLUMN, features_for
from sadi_forecast.models import design
from sadi_forecast.weather import build_weather

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=40)
    args = p.parse_args(argv)
    table = pd.read_parquet(INTERIM / "features_daily.parquet")
    postop = _dates(pd.read_parquet(INTERIM / "d8_postop_versions.parquet"))
    supply = _dates(pd.read_parquet(INTERIM / "d7_supply_hourly.parquet"))
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))
    weights = pd.read_csv(ROOT / "results" / "point_weights.csv", index_col="point")
    gfs = weather_daily(
        build_weather(ROOT / "data" / "raw" / "open_meteo", "gfs_prev"), GFS_COLUMN
    )
    full = design(table, "gfs", "gfs")
    candidates = [
        d
        for d in table.index
        if d >= dt.date(2021, 5, 1) and pd.notna(full.at[d, "d_t"])
    ]
    days = sorted(random.Random(0).sample(candidates, args.n))
    bad = 0
    for day in days:
        f = features_for(day, postop, supply, b1, gfs, weights["weight"])
        live = design(f, "gfs", "gfs").loc[day]
        ref = full.loc[day]
        for col in full.columns:
            a, b = live[col], ref[col]
            same = (
                (pd.isna(a) and pd.isna(b))
                or a == b
                or (isinstance(a, float) and np.isclose(a, b, rtol=1e-9, atol=1e-9))
            )
            if not same:
                bad += 1
                print(f"{day} {col}: live {a} vs table {b}")
        if abs(f["ref_mwh"].loc[day] - table["ref_mwh"].loc[day]) > 1e-6:
            bad += 1
            print(f"{day} ref_mwh differs")
    print(f"{len(days)} days checked, {bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
