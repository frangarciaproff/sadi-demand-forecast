"""Definition check of the live sources on post-test days (from 2026-10-01).

Question: is the quantity measured in production (D3, 5-min actual demand) the same as
the training target (D7 demanda local), and how do B1 (programmed net demand, D6) and
CAMMESA's intraday forecast (D2 demPrevista) relate to it?

Only days after the test period (TEST_END = 2026-09-30) are used, so the test set is not
touched. D5 is the bridge until the Síntesis base for October is published: D7 local /
D5 national was 0.994-1.003 per year in 2018-2025.

Usage (from the repository root, after build_tables.py --only d5 d6 [d7]):
    uv run python scripts/check_live_definition.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from sadi_forecast.config import TEST_END
from sadi_forecast.daily import b1_daily, daily_national
from sadi_forecast.live import by_date_daily, forecast_daily
from sadi_forecast.sintesis import latest_daily

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "cammesa"
INTERIM = ROOT / "data" / "interim"
START = dt.date(2026, 10, 1)
assert START > TEST_END, "the check must not use test-period days"

PAIRS = {
    "d3_over_d5": ("d3_mwh", "d5_mwh"),
    "d3_over_d7_local": ("d3_mwh", "d7_local_mwh"),
    "d3_over_b1": ("d3_mwh", "b1_mwh"),
    "d5_over_b1": ("d5_mwh", "b1_mwh"),
    "prevista_over_b1": ("d2_prevista_mwh", "b1_mwh"),
    "prevista_over_d3": ("d2_prevista_mwh", "d3_mwh"),
}


def main() -> int:
    days = pd.DataFrame({"d3_mwh": by_date_daily(RAW)})
    days["d2_prevista_mwh"] = forecast_daily(RAW)

    d5 = daily_national(pd.read_parquet(INTERIM / "d5_area_hourly.parquet"))
    days["d5_mwh"] = pd.Series(
        d5.to_numpy(), index=[t.date() for t in pd.DatetimeIndex(d5.index)]
    )
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))
    days["b1_mwh"] = b1.set_index("target_date")["energy_mwh"]
    d7_path = INTERIM / "d7_sintesis_type_hourly.parquet"
    if d7_path.exists():
        d7 = pd.read_parquet(d7_path)
        d7["date"] = pd.to_datetime(d7["date"]).dt.date
        days["d7_local_mwh"] = latest_daily(d7).set_index("date")["local_mwh"]
    else:
        days["d7_local_mwh"] = float("nan")

    days = days[[d > TEST_END and d >= START for d in days.index]].sort_index()
    for name, (num, den) in PAIRS.items():
        days[name] = days[num] / days[den]

    stats = {}
    for name in PAIRS:
        s = days[name].dropna()
        stats[name] = (
            {
                "n": len(s),
                "median": round(float(s.median()), 4),
                "min": round(float(s.min()), 4),
                "max": round(float(s.max()), 4),
            }
            if len(s)
            else {"n": 0}
        )
    summary = {"start": START.isoformat(), "last_day": str(days.index.max()), **stats}

    (INTERIM / "eda").mkdir(parents=True, exist_ok=True)
    days.to_csv(INTERIM / "eda" / "live_definition_daily.csv")
    out = ROOT / "results" / "eda"
    out.mkdir(parents=True, exist_ok=True)
    (out / "live_definition_check.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    cols = ["d3_mwh", "d5_mwh", "b1_mwh", "d2_prevista_mwh", *PAIRS]
    print(days[cols].round(4).to_string())
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
