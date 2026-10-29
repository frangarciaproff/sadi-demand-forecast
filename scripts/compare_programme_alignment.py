"""Operator hourly programme: as published vs aligned to D7's hours.

Supplement to the pre-registered v2 comparisons (SPEC 11), which used the programme as
published (D6 t01..t24). The programme's hour h is centred on h:00 while D7's hour h
covers (h-1):00..h:00 (results/checks/provisional_hourly.json); the aligned programme
is hourly.align_programme. Nothing about the model changes: the saved S1 forecasts of
the validation and the test year are re-scored against both versions of the benchmark
on the same days.

Writes results/checks/programme_alignment.json.

Usage (after backtest_hourly.py and evaluate_test_hourly.py):
    uv run python scripts/compare_programme_alignment.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_hourly import daily_ape, summary
from sadi_forecast.evaluation import block_bootstrap_ci, diebold_mariano
from sadi_forecast.hourly import HOURS, align_programme, programme_hourly

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RUNS = {
    "validation": INTERIM / "backtest" / "hourly_validation.parquet",
    "test_daily_totals_already_seen": INTERIM
    / "test"
    / "test_evaluation_hourly.parquet",
}


def _wide(saved: pd.DataFrame, name: str) -> pd.DataFrame:
    w = saved[[f"{name}_h{h:02d}" for h in HOURS]].copy()
    w.columns = HOURS
    return w


def main() -> int:
    aligned_all = align_programme(
        programme_hourly(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))
    )
    out: dict[str, Any] = {}
    for run, path in RUNS.items():
        saved = pd.read_parquet(path)
        actual, s1, b1 = (_wide(saved, k) for k in ("actual", "S1", "B1"))
        aligned = aligned_all.reindex(saved.index)
        days = [
            d
            for d in saved.index
            if not b1.loc[d].isna().any() and not aligned.loc[d].isna().any()
        ]
        a1 = daily_ape(s1, actual, days)
        res: dict[str, Any] = {
            "days": len(days),
            "S1": summary(s1, actual, days),
            "B1_as_published": summary(b1, actual, days),
            "B1_aligned": summary(aligned, actual, days),
        }
        for name, frame in (("as_published", b1), ("aligned", aligned)):
            ab = daily_ape(frame, actual, days)
            res[f"dm_s1_vs_b1_{name}_two_sided"] = diebold_mariano(
                a1, ab, alternative="two-sided"
            )
            res[f"ci95_hourly_mape_s1_minus_b1_{name}"] = block_bootstrap_ci(
                pd.concat([a1, ab], axis=1),
                lambda a: float(a[:, 0].mean() - a[:, 1].mean()),
            )
        out[run] = res
    folder = ROOT / "results" / "checks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "programme_alignment.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
