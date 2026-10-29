"""Baselines B0 (seasonal naive) and B1 (operator programme) on training and validation.

B0 for day D: the reference level ref_mwh (median of the same weekday over the
previous four weeks, as known at the issue time; features.py). B1: the operator's
programme for D (net demand + losses + pumping). Errors are percentages of the
definitive target. The test period is not read.

Writes results/baselines.json.

Usage (after build_features.py):
    uv run python scripts/baselines.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from sadi_forecast.config import TEST_START

ROOT = Path(__file__).resolve().parents[1]
PERIODS = {
    "training": (dt.date(2018, 1, 1), dt.date(2024, 9, 30)),
    "validation": (dt.date(2024, 10, 1), dt.date(2025, 9, 30)),
}
assert all(end < TEST_START for _, end in PERIODS.values())


def scores(pred: pd.Series, actual: pd.Series) -> dict[str, float | int]:
    pct = (100 * (pred / actual - 1)).dropna()
    return {
        "n_days": len(pct),
        "mape_pct": round(float(pct.abs().mean()), 3),
        "mae_gwh": round(float((pred - actual).abs().mean() / 1000), 3),
        "bias_pct": round(float(pct.mean()), 3),
        "spread_sd_pct": round(float(pct.std()), 3),
        "p90_abs_pct": round(float(pct.abs().quantile(0.9)), 3),
    }


def main() -> int:
    f = pd.read_parquet(ROOT / "data" / "interim" / "features_daily.parquet")
    b0 = f["ref_mwh"]
    out: dict[str, object] = {}
    for name, (start, end) in PERIODS.items():
        rows = f[[start <= d <= end for d in f.index]]
        idx = rows.index
        both = idx[b0.loc[idx].notna().to_numpy() & rows["b1_total_mwh"].notna()]
        out[name] = {
            "B0_seasonal_naive": scores(b0.loc[idx], rows["target_mwh"]),
            "B1_operator_programme": scores(rows["b1_total_mwh"], rows["target_mwh"]),
            "common_days": len(both),
            "B0_missing_days": int(b0.loc[idx].isna().sum()),
        }
    text = json.dumps(out, indent=2)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "baselines.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
