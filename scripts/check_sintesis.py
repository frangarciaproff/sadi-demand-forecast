"""EDA check of the Síntesis Mensual hourly demand (D7) as target source (O13).

1. Coverage per base: first/last day, days with a number of hours other than 24.
2. Revisions: the same day in different bases (earliest vs latest base).
3. Definition: daily D7 "demanda local" and "demanda total" (bases up to 2023-12
   only, so through 2023) against B1 (programmed net
   demand, D6), D1 gross energy and D5 national (sum of areas), per year.
4. Province sheet: sum of provinces against D7 local and total.

Uses only days up to 2025-09-30 (EDA rule). Daily detail goes to data/interim/eda/
(not committed); aggregate statistics to results/eda/sintesis_check.json.

Usage (from the repository root, after build_tables.py --only d7):
    uv run python scripts/check_sintesis.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from sadi_forecast.config import EDA_CUTOFF as CUTOFF
from sadi_forecast.daily import b1_daily, daily_national
from sadi_forecast.sintesis import daily_by_base, latest_daily

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
REVISION_FLAG_PCT = 0.1


def _ratio_stats(s: pd.Series) -> dict[str, float | int]:
    s = s.dropna()
    return {
        "n": len(s),
        "median": round(float(s.median()), 4),
        "p05": round(float(s.quantile(0.05)), 4),
        "p95": round(float(s.quantile(0.95)), 4),
    }


def main() -> int:
    hourly = pd.read_parquet(INTERIM / "d7_sintesis_type_hourly.parquet")
    hourly["date"] = pd.to_datetime(hourly["date"]).dt.date
    hourly = hourly[hourly["date"] <= CUTOFF]
    summary: dict[str, object] = {"cutoff": CUTOFF.isoformat()}

    by_base = daily_by_base(hourly)
    summary["coverage"] = [
        {
            "base": base,
            "first_day": str(g["date"].min()),
            "last_day": str(g["date"].max()),
            "days": len(g),
            "days_not_24h": int((g["n_hours"] != 24).sum()),
        }
        for base, g in by_base.groupby("base")
    ]

    ok = by_base.dropna(subset=["local_mwh"]).sort_values(["date", "base"])
    multi = ok.groupby("date").filter(lambda g: len(g) > 1)
    if not multi.empty:
        ends = multi.groupby("date")["local_mwh"].agg(["first", "last"])
        rev = (100 * (ends["last"] / ends["first"] - 1)).abs()
        summary["revisions_local_abs_pct"] = {
            "days": len(rev),
            "median": round(float(rev.median()), 4),
            "p95": round(float(rev.quantile(0.95)), 4),
            "max": round(float(rev.max()), 4),
            f"days_above_{REVISION_FLAG_PCT}pct": int((rev > REVISION_FLAG_PCT).sum()),
        }

    days = latest_daily(hourly).set_index("date")
    # Bases from 2024-12 omit total demand: take it from the latest base that has it.
    with_total = ok.dropna(subset=["total_mwh"]).groupby("date").last()
    days["total_mwh"] = with_total["total_mwh"]
    days["total_base"] = with_total["base"]
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))
    days["b1_mwh"] = b1.set_index("target_date")["energy_mwh"]
    d1 = pd.read_parquet(INTERIM / "d1_daily.parquet")
    days["d1_gross_mwh"] = d1.assign(date=pd.to_datetime(d1["date"]).dt.date).set_index(
        "date"
    )["gross_energy_mwh"]
    d5 = pd.read_parquet(INTERIM / "d5_area_hourly.parquet")
    d5_nat = daily_national(d5)
    days["d5_mwh"] = pd.Series(
        d5_nat.to_numpy(), index=[t.date() for t in pd.DatetimeIndex(d5_nat.index)]
    )

    pairs = {
        "local_over_b1": ("local_mwh", "b1_mwh"),
        "total_over_b1": ("total_mwh", "b1_mwh"),
        "local_over_d1_gross": ("local_mwh", "d1_gross_mwh"),
        "total_over_d1_gross": ("total_mwh", "d1_gross_mwh"),
        "local_over_d5": ("local_mwh", "d5_mwh"),
    }
    for name, (num, den) in pairs.items():
        days[name] = days[num] / days[den]
    days["year"] = [d.year for d in days.index]
    by_year: dict[str, dict[int, dict[str, float | int]]] = {
        name: {int(str(y)): _ratio_stats(g[name]) for y, g in days.groupby("year")}
        for name in pairs
    }
    summary["definition_by_year"] = by_year

    prov_path = INTERIM / "d7_sintesis_province_hourly.parquet"
    if prov_path.exists():
        prov = pd.read_parquet(prov_path)
        prov["date"] = pd.to_datetime(prov["date"]).dt.date
        prov = prov[(prov["date"] <= CUTOFF) & (prov["province"] != "total")]
        latest_base = prov.groupby("date")["base"].transform("max")
        prov = prov[prov["base"] == latest_base]
        prov_day = prov.groupby("date")["mwh"].sum(min_count=1)
        days["prov_sum_mwh"] = prov_day
        summary["provinces"] = sorted(prov["province"].unique())
        summary["province_sum_over_local"] = _ratio_stats(
            days["prov_sum_mwh"] / days["local_mwh"]
        )
        summary["province_sum_over_total"] = _ratio_stats(
            days["prov_sum_mwh"] / days["total_mwh"]
        )

    (INTERIM / "eda").mkdir(parents=True, exist_ok=True)
    days.to_csv(INTERIM / "eda" / "sintesis_daily_check.csv")
    out = ROOT / "results" / "eda"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sintesis_check.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    table = pd.DataFrame(
        {
            name: {y: v["median"] for y, v in stats.items()}
            for name, stats in by_year.items()
        }
    )
    print("Coverage:", json.dumps(summary["coverage"], indent=1))
    print("Revisions:", summary.get("revisions_local_abs_pct"))
    print("Median ratios by year:")
    print(table.to_string())
    for key in ("province_sum_over_local", "province_sum_over_total"):
        if key in summary:
            print(key, summary[key])
    return 0


if __name__ == "__main__":
    sys.exit(main())
