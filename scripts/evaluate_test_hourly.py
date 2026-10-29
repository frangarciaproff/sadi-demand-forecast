"""Single evaluation of v2 (hourly curve) on the test year 2025-10-01 → 2026-09-30.

SPEC 11: evaluated once, after the validation decision (results/backtest/
hourly_validation.json) and the R6 audit. Labelled "daily totals already seen": the v1
daily forecast it scales (F-hyb, data/interim/test/test_evaluation_seen_hyb.parquet) was
scored on this year; the shape model was not.

The script refuses to run if its output exists.
Writes results/test/test_evaluation_hourly.json and
data/interim/test/test_evaluation_hourly.parquet.

Usage (from scripts/):
    uv run python evaluate_test_hourly.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_hourly import compare_hourly, hourly_forecasts, save_hourly
from sadi_forecast.config import TEST_END, TEST_START
from sadi_forecast.evaluation import block_bootstrap_ci, diebold_mariano

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "results" / "test" / "test_evaluation_hourly.json"


def main() -> int:
    if OUT.exists():
        print(f"{OUT} exists: the test is evaluated once. Not running.")
        return 1
    decision = json.loads(
        (ROOT / "results" / "backtest" / "hourly_validation.json").read_text()
    )["decision"]["shape_model"]
    daily_fc = pd.read_parquet(INTERIM / "test" / "test_evaluation_seen_hyb.parquet")[
        "model"
    ]
    pred_s1, pred_s0, b1h, actual, days = hourly_forecasts(
        TEST_START, TEST_END, daily_fc
    )
    cmp, a1, a0, ab, common = compare_hourly(pred_s1, pred_s0, b1h, actual, days)
    chosen = a1 if decision == "S1" else a0
    result: dict[str, Any] = {
        "label": "daily totals already seen",
        "shape_model": decision,
        "daily_forecast": "v1 F-hyb test forecasts (test_evaluation_seen_hyb)",
        "period": [TEST_START, TEST_END],
        **cmp,
        "dm_chosen_vs_b1_two_sided": diebold_mariano(
            chosen, ab, alternative="two-sided"
        ),
        "ci95_hourly_mape_chosen_minus_b1": block_bootstrap_ci(
            pd.concat([chosen, ab], axis=1),
            lambda a: float(a[:, 0].mean() - a[:, 1].mean()),
        ),
    }
    q = pd.DatetimeIndex(common).to_period("Q")
    apes = {"S1": a1, "S0": a0, "B1": ab}
    result["by_quarter_hourly_mape"] = {
        str(p): {k: round(float(v[q == p].mean()), 3) for k, v in apes.items()}
        for p in sorted(set(q))
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    save_hourly(
        INTERIM / "test" / "test_evaluation_hourly.parquet",
        {"S1": pred_s1, "S0": pred_s0, "B1": b1h, "actual": actual},
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
