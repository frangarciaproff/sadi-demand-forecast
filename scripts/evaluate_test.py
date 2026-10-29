"""Single evaluation of the test year 2025-10-01 → 2026-09-30 (SPEC 4.3 step 4, 5).

Configuration frozen in DECISIONS 2026-10-29 (step 3 result): F-tree, 5-year window,
M-fc (GFS in training and evaluation), monthly refits with the label embargo.
Thresholds S1 and S2 fixed in SPEC 5 before this script was run.

The test is evaluated once: the script refuses to run if its output exists.
Writes results/test/test_evaluation.json; daily forecasts to data/interim/test/.

Usage:
    uv run python scripts/evaluate_test.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from backtest import Runner, abs_pct, compare, out_of_range, read_step
from sadi_forecast.config import TEST_END, TEST_START
from sadi_forecast.daily import b1_daily
from sadi_forecast.evaluation import block_bootstrap_ci, diebold_mariano, scores
from sadi_forecast.features import valid_versions

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "results" / "test" / "test_evaluation.json"
S1_SKILL = 0.50
S2_MARGIN_PP = 0.50


def first_daily_reports(days: list[dt.date]) -> pd.DataFrame:
    """Provisional actual of each day: its first daily report and the validity flag."""
    postop = pd.read_parquet(INTERIM / "d8_postop_versions.parquet")
    postop["date"] = pd.to_datetime(postop["date"]).dt.date
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))
    v = valid_versions(postop, b1)
    v = v[(v["kind"] == "daily") & v["date"].isin(days)]
    first = v.sort_values("published_art").groupby("date").head(1)
    return first.set_index("date")[["value_mwh", "valid"]]


def main() -> int:
    if OUT.exists():
        print(f"{OUT} exists: the test is evaluated once. Not running.")
        return 1
    family = read_step("step1_family")["decision"]["family"]
    window = read_step("step2_window")["decision"]["window"]
    source = read_step("step3_weather")["decision"]["weather_source"]
    f = pd.read_parquet(INTERIM / "features_daily.parquet")
    f = f[[d <= TEST_END for d in f.index]]
    run = Runner(f)
    model = run.run(family, window, source, TEST_START, TEST_END).rename("model")
    tf = f.loc[[TEST_START <= d <= TEST_END for d in f.index]]
    actual = f["target_mwh"]
    preds = {"model": model, "B0": tf["ref_mwh"], "B1": tf["b1_total_mwh"]}

    result: dict[str, Any] = {
        "configuration": {"family": family, "window": window, "weather": source},
        "period": [TEST_START, TEST_END],
        "forecast_days": len(model),
        "definitive": compare(preds, tf),
    }
    common = pd.concat(preds, axis=1).dropna().index
    err = {k: (p.loc[common] - actual.loc[common]).abs() for k, p in preds.items()}
    ape = {k: abs_pct(p.loc[common], actual.loc[common]) for k, p in preds.items()}
    skill = float(1 - err["model"].mean() / err["B0"].mean())
    skill_ci = block_bootstrap_ci(
        pd.concat([err["model"], err["B0"]], axis=1),
        lambda a: float(1 - a[:, 0].mean() / a[:, 1].mean()),
    )
    diff = float(ape["model"].mean() - ape["B1"].mean())
    diff_ci = block_bootstrap_ci(
        pd.concat([ape["model"], ape["B1"]], axis=1),
        lambda a: float(a[:, 0].mean() - a[:, 1].mean()),
    )
    result["success"] = {
        "S1": {
            "skill_vs_B0": round(skill, 4),
            "ci95": skill_ci,
            "threshold": S1_SKILL,
            "pass": bool(skill >= S1_SKILL and skill_ci[0] > 0),
        },
        "S2": {
            "mape_difference_model_minus_B1_pp": round(diff, 4),
            "ci95": diff_ci,
            "margin_pp": S2_MARGIN_PP,
            "pass": bool(diff_ci[1] < S2_MARGIN_PP),
        },
        "common_days": len(common),
    }
    result["dm_model_vs_B1_two_sided"] = diebold_mariano(
        ape["model"], ape["B1"], alternative="two-sided"
    )

    flags = out_of_range(f).loc[common]
    oor = flags.index[flags["out_of_range"]]
    result["out_of_range_days"] = {
        "n": len(oor),
        "scores": {k: scores(p.loc[oor], actual.loc[oor]) for k, p in preds.items()}
        if len(oor)
        else {},
    }
    result["load_shedding_days"] = "not reported: no source list yet (SPEC O10)"
    tq = pd.DatetimeIndex(common).to_period("Q")
    result["by_quarter_mape"] = {
        str(q): {
            k: round(float(v.loc[common[tq == q]].mean()), 3) for k, v in ape.items()
        }
        for q in sorted(set(tq))
    }

    prov = first_daily_reports(list(tf.index))
    pcommon = common.intersection(prov.index)
    pa = prov.loc[pcommon, "value_mwh"]
    kept = prov.loc[pcommon].index[prov.loc[pcommon, "valid"].to_numpy()]
    result["provisional"] = {
        "note": "actual = first daily report (supply - programmed exports); biased "
        "towards B1 because the validity check uses B1 (SPEC 4.5)",
        "all_days": {k: scores(p.loc[pcommon], pa) for k, p in preds.items()},
        "rejected_days": int(len(pcommon) - len(kept)),
        "without_rejected": {
            k: scores(p.loc[kept], pa.loc[kept]) for k, p in preds.items()
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    (INTERIM / "test").mkdir(parents=True, exist_ok=True)
    pd.concat(preds, axis=1).to_parquet(INTERIM / "test" / "test_forecasts.parquet")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
