"""O14: thresholds of the validity check of daily reports (SPEC 2.2), training days.

Ratios, computed with definitive values (complements) on every training day:
    r1 = target / B1 total                      (operator programme, same definition)
    r2 = target / median of the same weekday in the previous 4 weeks
k1, k2 = quantiles of |r - 1| (99, 99.5, 99.9 %). Then the check is applied to every
archived daily report (provisional = daily supply - programmed exports) to measure
how many are flagged and whether the known gross errors are caught.

Uses only training days (2018-01-01 → 2024-09-30). Daily detail goes to
data/interim/eda/ (not committed); the summary to results/eda/validity_check.json.

Usage (after build_tables.py --only d6 d7 d8):
    uv run python scripts/check_validity.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from sadi_forecast.daily import b1_daily
from sadi_forecast.targets import definitive_daily, provisional_daily

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
TRAIN_START = dt.date(2018, 1, 1)
TRAIN_END = dt.date(2024, 9, 30)
QUANTILES = (0.99, 0.995, 0.999)
KNOWN_ERRORS = ["2022-05-15", "2022-08-15", "2023-11-14"]


def same_weekday_median(series: pd.Series, weeks: int = 4) -> pd.Series:
    """Median of the same weekday over the previous `weeks` weeks (valid values)."""
    s = series.sort_index()
    s.index = pd.DatetimeIndex(s.index)
    s = s.asfreq("D")
    lagged = pd.concat([s.shift(7 * k) for k in range(1, weeks + 1)], axis=1)
    med = lagged.median(axis=1, skipna=True)
    med[lagged.notna().sum(axis=1) < weeks // 2] = float("nan")
    med.index = [t.date() for t in med.index]
    return med


def main() -> int:
    postop = pd.read_parquet(INTERIM / "d8_postop_versions.parquet")
    postop["date"] = pd.to_datetime(postop["date"]).dt.date
    supply = pd.read_parquet(INTERIM / "d7_supply_hourly.parquet")
    supply["date"] = pd.to_datetime(supply["date"]).dt.date
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))

    target = definitive_daily(postop, supply).set_index("date")
    in_train = [TRAIN_START <= d <= TRAIN_END for d in target.index]
    target = target[in_train]
    t = target["target_mwh"]
    b1_total = b1.set_index("target_date")["b1_total_mwh"]
    med = same_weekday_median(t)
    days = pd.DataFrame(
        {"target_mwh": t, "b1_total_mwh": b1_total, "weekday_median": med}
    ).loc[t.index]
    days["r1"] = days["target_mwh"] / days["b1_total_mwh"]
    days["r2"] = days["target_mwh"] / days["weekday_median"]

    k: dict[str, dict[str, float]] = {}
    for r in ("r1", "r2"):
        dev = (days[r] - 1).abs().dropna()
        k[r] = {f"q{q * 100:g}": round(float(dev.quantile(q)), 4) for q in QUANTILES}
        k[r]["n"] = len(dev)
        k[r]["max"] = round(float(dev.max()), 4)

    prov = provisional_daily(postop, b1)
    prov = prov[[TRAIN_START <= d <= TRAIN_END for d in prov["date"]]].copy()
    prov["r1"] = prov["provisional_mwh"] / prov["b1_total_mwh"]
    prov["r2"] = prov["provisional_mwh"] / prov["date"].map(med)
    prov["dev_vs_definitive"] = prov["provisional_mwh"] / prov["date"].map(t) - 1
    checks = {}
    for q in QUANTILES:
        k1, k2 = k["r1"][f"q{q * 100:g}"], k["r2"][f"q{q * 100:g}"]
        bad = ((prov["r1"] - 1).abs() > k1) | ((prov["r2"] - 1).abs() > k2)
        gross = prov["dev_vs_definitive"].abs() > 0.02
        checks[f"q{q * 100:g}"] = {
            "k1": k1,
            "k2": k2,
            "reports": len(prov),
            "flagged": int(bad.sum()),
            "reports_off_by_more_than_2pct": int(gross.sum()),
            "of_those_flagged": int((bad & gross).sum()),
            "known_errors_flagged": {
                d: bool(bad[prov["date"] == dt.date.fromisoformat(d)].any())
                for d in KNOWN_ERRORS
            },
        }
    dev = prov["dev_vs_definitive"].abs().dropna()
    summary = {
        "period": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
        "flags": target["flag"].value_counts().to_dict(),
        "multiple_complement_days": int((target["n_complements"] > 1).sum()),
        "complement_vs_d7_abs_pct": {
            "median": round(
                100
                * float(
                    (target["supply_mwh"] / target["supply7_mwh"] - 1).abs().median()
                ),
                4,
            ),
            "max": round(
                100
                * float((target["supply_mwh"] / target["supply7_mwh"] - 1).abs().max()),
                4,
            ),
        },
        "daily_vs_definitive_abs_pct": {
            "median": round(100 * float(dev.median()), 3),
            "p90": round(100 * float(dev.quantile(0.9)), 3),
            "p99": round(100 * float(dev.quantile(0.99)), 3),
            "max": round(100 * float(dev.max()), 3),
        },
        "thresholds": k,
        "check": checks,
        "documents_listed_under_another_day": int(
            postop["date_mismatch"].sum() if "date_mismatch" in postop else 0
        ),
        "worst_daily_reports": [
            {
                "date": str(row["date"]),
                "published": row["published"],
                "dev_vs_definitive_pct": round(100 * row["dev_vs_definitive"], 2),
                "r1": round(row["r1"], 3),
            }
            for row in prov.assign(a=prov["dev_vs_definitive"].abs())
            .sort_values("a", ascending=False)
            .head(15)
            .to_dict(orient="records")
        ],
        "complements_far_from_d7": [
            {
                "date": str(d),
                "complement_over_d7": round(row.supply_mwh / row.supply7_mwh, 4),
                "n_complements": int(row.n_complements),
            }
            for d, row in target[target["flag"] == "complement_far_from_d7"]
            .head(15)
            .iterrows()
        ],
    }
    (INTERIM / "eda").mkdir(parents=True, exist_ok=True)
    days.to_csv(INTERIM / "eda" / "validity_days.csv")
    prov.to_csv(INTERIM / "eda" / "validity_reports.csv", index=False)
    out = ROOT / "results" / "eda"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validity_check.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
