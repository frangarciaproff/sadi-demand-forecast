"""EDA check: national demand from D5 (sum of 9 areas) vs D1 gross energy, day by day.

Uses only data up to 2025-09-30 (EDA rule, SPEC 4.1). Requires the data/interim tables
from scripts/build_tables.py. Writes the daily detail to data/interim/eda/
(not committed) and only aggregate statistics to results/eda/ (committed).

Usage (from the repository root):
    uv run python scripts/check_d5_vs_d1.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
CUTOFF = dt.date(2025, 9, 30)
N_AREAS = 9
OUTLIER_BAND = 0.03  # |ratio - yearly median| above this is an outlier
SHIFT_MATCH = (
    0.01  # a ±1-day shift "explains" an outlier if it brings it within this band
)


def national_by_version(d5: pd.DataFrame) -> pd.DataFrame:
    """Sum of areas per (version, date).

    NaN unless all 9 areas are present and none is missing.
    """
    grp = d5.groupby(["doc_id", "pub_date", "pub_time", "date"])
    out = grp.agg(
        energy_mwh=("energy_mwh", "sum"),
        n_areas=("area", "nunique"),
        n_missing=("missing", "sum"),
    ).reset_index()
    complete = (out["n_areas"] == N_AREAS) & (out["n_missing"] == 0)
    out.loc[~complete, "energy_mwh"] = float("nan")
    return out


def first_and_last(nat: pd.DataFrame) -> pd.DataFrame:
    ok = nat.dropna(subset=["energy_mwh"]).sort_values(
        ["date", "pub_date", "pub_time", "doc_id"]
    )
    first = ok.groupby("date").first()[["energy_mwh", "pub_date"]]
    last = ok.groupby("date").last()[["energy_mwh", "pub_date"]]
    return first.join(last, lsuffix="_first", rsuffix="_last").reset_index()


def main() -> int:
    d5 = pd.read_parquet(INTERIM / "d5_area_hourly.parquet")
    d1_table = pd.read_parquet(INTERIM / "d1_daily.parquet")
    d5 = d5[d5["date"] <= CUTOFF]
    d1_table = d1_table[d1_table["date"] <= CUTOFF]
    gross: dict[dt.date, float] = dict(
        zip(d1_table["date"], d1_table["gross_energy_mwh"], strict=True)
    )

    nat = national_by_version(d5)
    days = first_and_last(nat)
    one_day = dt.timedelta(days=1)
    days["gross"] = [gross.get(d) for d in days["date"]]
    days["gross_prev"] = [gross.get(d - one_day) for d in days["date"]]
    days["gross_next"] = [gross.get(d + one_day) for d in days["date"]]
    days = days.dropna(subset=["gross"])
    days["year"] = pd.to_datetime(days["date"]).dt.year
    days["ratio"] = days["energy_mwh_last"] / days["gross"]
    days["ratio_first"] = days["energy_mwh_first"] / days["gross"]
    days["revision_pct"] = 100 * (
        days["energy_mwh_last"] / days["energy_mwh_first"] - 1
    )

    med = days.groupby("year")["ratio"].transform("median")
    days["outlier"] = (days["ratio"] - med).abs() > OUTLIER_BAND
    for col, ref in (("ratio_prev", "gross_prev"), ("ratio_next", "gross_next")):
        days[col] = days["energy_mwh_last"] / days[ref]
    shift_fit = pd.concat(
        [(days["ratio_prev"] - med).abs(), (days["ratio_next"] - med).abs()], axis=1
    )
    days["shift_explains"] = days["outlier"] & (shift_fit.min(axis=1) < SHIFT_MATCH)

    (INTERIM / "eda").mkdir(parents=True, exist_ok=True)
    days.to_csv(INTERIM / "eda" / "d5_vs_d1_daily.csv", index=False)

    yearly = days.groupby("year").agg(
        n_days=("ratio", "size"),
        ratio_median=("ratio", "median"),
        ratio_p05=("ratio", lambda s: s.quantile(0.05)),
        ratio_p95=("ratio", lambda s: s.quantile(0.95)),
        outliers=("outlier", "sum"),
        outliers_explained_by_1day_shift=("shift_explains", "sum"),
    )
    rev = days["revision_pct"].abs()
    summary = {
        "cutoff": CUTOFF.isoformat(),
        "versions": int(nat["doc_id"].nunique()),
        "days_compared": len(days),
        "incomplete_version_days": int(nat["energy_mwh"].isna().sum()),
        "revision_abs_pct": {
            "median": round(float(rev.median()), 4),
            "p95": round(float(rev.quantile(0.95)), 4),
            "max": round(float(rev.max()), 4),
        },
        "yearly": yearly.round(4).reset_index().to_dict(orient="records"),
    }
    out = ROOT / "results" / "eda"
    out.mkdir(parents=True, exist_ok=True)
    (out / "d5_vs_d1_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(yearly.round(4).to_string())
    print(json.dumps({k: v for k, v in summary.items() if k != "yearly"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
