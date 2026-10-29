"""Post-hoc checks of the re-audit 2026-10-29 (validation only; v1 replacement rule in
DECISIONS 2026-10-29).

(a) Step 1 under M-fc: F-tree vs F-hyb, 5 years, GFS in training and evaluation, plus
    the extremes backtest with yearly refits 2022-01-01 → 2025-09-30.
(b) Bias-corrected M-obs: ERA5 training; the GFS temperature of D is corrected per
    point by its mean GFS - ERA5 difference over 2021-03-25 → 2024-09-30, and degree
    days are recomputed per point. Both families, 5 years.

Writes results/backtest/sensitivity_reaudit.json. The test period is not loaded.

Usage (after backtest.py):
    uv run python scripts/sensitivity.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from backtest import (
    EXT_END,
    SOURCES,
    VAL_END,
    VAL_START,
    Runner,
    abs_pct,
    compare,
    load,
    out_of_range,
    save,
)
from sadi_forecast.evaluation import diebold_mariano, scores
from sadi_forecast.features import reference, weather_daily, weighted_degree_days
from sadi_forecast.weather import build_weather

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "open_meteo"
BIAS_PERIOD = (dt.date(2021, 3, 25), dt.date(2024, 9, 30))
EXT_FC_START = dt.date(2022, 1, 1)
V1 = ("tree", "5y", "fc")


def add_bias_corrected(f: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Columns *_gfsbc: per-point bias-corrected GFS, weighted like the others."""
    era5 = weather_daily(build_weather(RAW, "era5"), "temperature_2m")
    gfs = weather_daily(build_weather(RAW, "gfs_prev"), "temperature_2m_previous_day2")
    in_bias = [BIAS_PERIOD[0] <= d <= BIAS_PERIOD[1] for d in gfs.index]
    bias = (gfs[in_bias] - era5.reindex(gfs.index)[in_bias]).mean()
    weights = pd.read_csv(ROOT / "results" / "point_weights.csv", index_col="point")
    corrected = (gfs - bias).reindex(f.index)
    wdd = weighted_degree_days(corrected, weights["weight"], "gfsbc")
    g = f.join(wdd)
    refs = reference(g, list(wdd.columns))
    g = g.join(refs[[f"ref_{c}" for c in wdd.columns]])
    return g, {str(k): round(float(v), 3) for k, v in bias.items()}


def main() -> int:
    f, bias = add_bias_corrected(load())
    SOURCES["obs_bc"] = ("era5", "era5", "gfsbc", "era5")
    run = Runner(f)
    actual = f["target_mwh"]
    vf = f.loc[[VAL_START <= d <= VAL_END for d in f.index]]
    preds = {
        f"{fam}_{src}": run.run(fam, "5y", src, VAL_START, VAL_END)
        for fam in ("tree", "hyb")
        for src in ("fc", "obs_bc")
    }
    v1 = preds["_".join((V1[0], V1[2]))]
    result: dict[str, Any] = {"gfs_minus_era5_bias_c_per_point": bias}
    result["validation"] = compare({**preds, "B0": vf["ref_mwh"]}, vf)
    result["dm_vs_v1_two_sided"] = {
        k: diebold_mariano(
            abs_pct(p, actual), abs_pct(v1, actual), alternative="two-sided"
        )
        for k, p in preds.items()
        if k != "tree_fc"
    }

    ext = {
        fam: run.run(fam, "5y", "fc", EXT_FC_START, EXT_END, yearly=True)
        for fam in ("tree", "hyb")
    }
    flags = out_of_range(f)
    common = pd.concat(ext, axis=1).dropna().index
    fl = flags.loc[common]
    oor = fl.index[fl["out_of_range"]]
    result["extremes_backtest_fc"] = {
        "period": [min(common), max(common)],
        "days": len(common),
        "out_of_range_days": len(oor),
        "all_days": {
            k: scores(p.loc[common], actual.loc[common]) for k, p in ext.items()
        },
        "out_of_range": {
            k: scores(p.loc[oor], actual.loc[oor]) for k, p in ext.items()
        },
    }
    sc = result["validation"]["scores"]
    v1_mape = sc["tree_fc"]["mape_pct"]
    hyb_ext_ok = (
        result["extremes_backtest_fc"]["out_of_range"]["hyb"]["mape_pct"]
        < result["extremes_backtest_fc"]["out_of_range"]["tree"]["mape_pct"]
    )
    replace = {}
    for k, dm in result["dm_vs_v1_two_sided"].items():
        better = sc[k]["mape_pct"] < v1_mape and float(dm["p_value"]) < 0.05
        if k.startswith("hyb"):
            better = better and hyb_ext_ok
        replace[k] = bool(better)
    result["replacement_rule"] = {
        "v1_validation_mape": v1_mape,
        "hyb_passes_extremes_rule_under_fc": bool(hyb_ext_ok),
        "replaces_v1": replace,
    }
    preds.update({f"ext_fc_{k}": v for k, v in ext.items()})
    save("sensitivity_reaudit", result, preds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
