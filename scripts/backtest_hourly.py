"""v2 validation (SPEC 11): hourly shares S0 vs S1, on top of the v1 daily forecast.

Validation 2024-10-01 → 2025-09-30, monthly refits with the label embargo, 5-year
window, GFS days only. The v1 daily forecast of each validation day is the validation
forecast of the v1 configuration (F-hyb, 5 years, M-fc), column hyb_fc of
data/interim/backtest/sensitivity_reaudit.parquet. The test period is not loaded.

Writes results/backtest/hourly_validation.json (decision included).

Usage (after sensitivity.py):
    uv run python scripts/backtest_hourly.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from sadi_forecast.config import EDA_CUTOFF
from sadi_forecast.daily import b1_daily
from sadi_forecast.evaluation import block_bootstrap_ci, diebold_mariano
from sadi_forecast.features import valid_versions
from sadi_forecast.hourly import (
    FEATURES,
    HOURS,
    T_COLS,
    TREES,
    definitive_hourly,
    design_hourly,
    hourly_temperature,
    programme_hourly,
    reference_shapes,
    shape_target,
    shares_from_model,
    version_shapes,
)
from sadi_forecast.targets import definitive_available_until
from sadi_forecast.weather import build_weather

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
VAL_START, VAL_END = dt.date(2024, 10, 1), dt.date(2025, 9, 30)
WINDOW_YEARS = 5
assert VAL_END <= EDA_CUTOFF


def _dates(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    df[col] = pd.to_datetime(df[col]).dt.date
    return df


def month_starts(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(d)
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def summary(
    pred: pd.DataFrame, actual: pd.DataFrame, days: list[dt.date]
) -> dict[str, Any]:
    p, a = pred.loc[days, HOURS], actual.loc[days, HOURS]
    e = 100 * (p / a - 1)
    peak_p, peak_a = p.max(axis=1), a.max(axis=1)
    pe = 100 * (peak_p / peak_a - 1)
    hour_err = (p.idxmax(axis=1) - a.idxmax(axis=1)).abs()
    return {
        "days": len(days),
        "hourly_mape_pct": round(float(e.abs().to_numpy().mean()), 3),
        "hourly_bias_pct": round(float(e.to_numpy().mean()), 3),
        "peak_mape_pct": round(float(pe.abs().mean()), 3),
        "peak_bias_pct": round(float(pe.mean()), 3),
        "peak_hour_mean_abs_error_h": round(float(hour_err.mean()), 2),
        "peak_hour_within_1h_share": round(float((hour_err <= 1).mean()), 3),
    }


def daily_ape(
    pred: pd.DataFrame, actual: pd.DataFrame, days: list[dt.date]
) -> pd.Series:
    e = (100 * (pred.loc[days, HOURS] / actual.loc[days, HOURS] - 1)).abs()
    return e.mean(axis=1)


def hourly_forecasts(
    start: dt.date, end: dt.date, daily_fc: pd.Series
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dt.date]]:
    """S1, S0 and B1 hourly forecasts and the definitive hourly actual for start..end.

    Data after `end` is not loaded. Returns (S1, S0, B1, actual, days with S1 and S0).
    """
    f = pd.read_parquet(INTERIM / "features_daily.parquet")
    f = f[[d <= end for d in f.index]]
    postop = _dates(pd.read_parquet(INTERIM / "d8_postop_versions.parquet"))
    postop = postop[[d <= end for d in postop["date"]]]
    supply = _dates(pd.read_parquet(INTERIM / "d7_supply_hourly.parquet"))
    supply = supply[[d <= end for d in supply["date"]]]
    programme = pd.read_parquet(INTERIM / "d6_programme_hourly.parquet")
    b1 = b1_daily(programme)
    prog = programme_hourly(programme)
    weights = pd.read_csv(ROOT / "results" / "point_weights.csv", index_col="point")
    raw = build_weather(ROOT / "data" / "raw" / "open_meteo", "gfs_prev")
    temp = hourly_temperature(raw, "temperature_2m_previous_day2", weights["weight"])
    temp = temp[[d <= end for d in temp.index]]

    actual = definitive_hourly(supply)
    shapes = version_shapes(valid_versions(postop, b1), prog)
    days = [d for d in f.index if d >= dt.date(2021, 4, 1)]
    s0, used = reference_shapes(shapes, days)
    x = design_hourly(f, s0, temp, used, days)
    y = shape_target(x, actual)
    dates = np.array(x["date"])

    s1_parts = []
    for r in month_starts(start, end):
        last = definitive_available_until(r)
        nxt = last + dt.timedelta(days=1)
        first = nxt.replace(year=nxt.year - WINDOW_YEARS)
        nxt_month = (r.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        train = (dates >= first) & (dates <= last) & y.notna().to_numpy()
        test = (dates >= r) & (dates < nxt_month) & (dates <= end)
        if not test.any():
            continue
        model = HistGradientBoostingRegressor(**TREES)
        model.fit(x.loc[train, FEATURES], y[train])
        pred = model.predict(x.loc[test, FEATURES])
        s1_parts.append(shares_from_model(x[test], pred))
    s1 = pd.concat(s1_parts)

    days_out = [
        d
        for d in s1.index
        if d in actual.index and d in daily_fc.index and not pd.isna(daily_fc[d])
    ]
    e_hat = daily_fc.loc[days_out]
    pred_s1 = s1.loc[days_out].mul(e_hat, axis=0)
    pred_s0 = s0.loc[days_out].mul(e_hat, axis=0)
    b1h = prog.reindex(days_out)[T_COLS].astype(float)
    b1h.columns = HOURS
    return pred_s1, pred_s0, b1h, actual.loc[days_out], days_out


def compare_hourly(
    pred_s1: pd.DataFrame,
    pred_s0: pd.DataFrame,
    b1h: pd.DataFrame,
    actual: pd.DataFrame,
    days: list[dt.date],
) -> tuple[dict[str, Any], pd.Series, pd.Series, pd.Series, list[dt.date]]:
    """Scores of S1, S0 and B1 on the days all three exist, and their daily APEs."""
    common = [d for d in days if not b1h.loc[d].isna().any()]
    result: dict[str, Any] = {
        "days_with_s0_s1": len(days),
        "common_days_with_b1": len(common),
        "S1": summary(pred_s1, actual, common),
        "S0": summary(pred_s0, actual, common),
        "B1": summary(b1h, actual, common),
    }
    a1, a0, ab = (daily_ape(p, actual, common) for p in (pred_s1, pred_s0, b1h))
    result["dm_s1_vs_s0_two_sided"] = diebold_mariano(a1, a0, alternative="two-sided")
    result["ci95_hourly_mape_s1_minus_s0"] = block_bootstrap_ci(
        pd.concat([a1, a0], axis=1), lambda a: float(a[:, 0].mean() - a[:, 1].mean())
    )
    return result, a1, a0, ab, common


def save_hourly(path: Path, preds: dict[str, pd.DataFrame]) -> None:
    saved = pd.concat(preds, axis=1)
    saved.columns = [f"{c[0]}_h{int(c[1]):02d}" for c in saved.columns.to_list()]
    path.parent.mkdir(parents=True, exist_ok=True)
    saved.to_parquet(path)


def main() -> int:
    daily_fc = pd.read_parquet(INTERIM / "backtest" / "sensitivity_reaudit.parquet")[
        "hyb_fc"
    ]
    pred_s1, pred_s0, b1h, actual, days = hourly_forecasts(VAL_START, VAL_END, daily_fc)
    cmp, a1, a0, ab, _ = compare_hourly(pred_s1, pred_s0, b1h, actual, days)
    result: dict[str, Any] = {"period": [VAL_START, VAL_END], **cmp}
    adopt = (
        result["S1"]["hourly_mape_pct"] < result["S0"]["hourly_mape_pct"]
        and float(result["dm_s1_vs_s0_two_sided"]["p_value"]) < 0.05
    )
    result["dm_chosen_vs_b1_two_sided"] = diebold_mariano(
        a1 if adopt else a0, ab, alternative="two-sided"
    )
    result["decision"] = {"shape_model": "S1" if adopt else "S0"}
    (ROOT / "results" / "backtest").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "backtest" / "hourly_validation.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    save_hourly(
        INTERIM / "backtest" / "hourly_validation.parquet",
        {"S1": pred_s1, "S0": pred_s0, "B1": b1h, "actual": actual},
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
