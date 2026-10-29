"""Backtest and decision sequence of SPEC 4.3 on validation (2024-10-01 → 2025-09-30).

Steps, each logged in results/backtest/<step>.json before the next one reads it:
    family   F-tree vs F-hyb (M-obs, all history) + extremes rolling-origin backtest
    window   3 years vs 5 years vs all (winning family, M-obs)
    weather  M-obs vs M-fc (winning family and window), both with forecast inputs
Rules fixed in DECISIONS 2026-10-29. The test period is never loaded: rows after
2025-09-30 are dropped on reading.

Monthly refits on the first day of each month; a refit on date r trains on labels
up to targets.definitive_available_until(r). Daily forecasts go to
data/interim/backtest/ (not committed).

Usage (after build_features.py):
    uv run python scripts/backtest.py --step family
    uv run python scripts/backtest.py --step window
    uv run python scripts/backtest.py --step weather
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sadi_forecast.config import EDA_CUTOFF
from sadi_forecast.evaluation import (
    acf_ljung_box,
    block_bootstrap_ci,
    diebold_mariano,
    pct_error,
    scores,
)
from sadi_forecast.models import FAMILIES, HybridModel, design, relative_target
from sadi_forecast.targets import definitive_available_until

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "results" / "backtest"
VAL_START, VAL_END = dt.date(2024, 10, 1), dt.date(2025, 9, 30)
EXT_START, EXT_END = dt.date(2021, 1, 1), dt.date(2025, 9, 30)
WINDOWS: dict[str, int | None] = {"3y": 3, "5y": 5, "all": None}
# weather source -> (training day, training reference, evaluation day and reference)
SOURCES = {
    "obs": ("era5", "era5", "gfs", "era5"),
    "fc": ("gfs", "gfs", "gfs", "gfs"),
    "oracle": ("era5", "era5", "era5", "era5"),
}
assert VAL_END <= EDA_CUTOFF


def load() -> pd.DataFrame:
    f = pd.read_parquet(INTERIM / "features_daily.parquet")
    f = f[[d <= VAL_END for d in f.index]]
    assert max(f.index) <= EDA_CUTOFF
    return f


def month_starts(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(d)
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def origins(
    start: dt.date, end: dt.date, yearly: bool
) -> list[tuple[dt.date, dt.date, dt.date]]:
    """(refit date, first, last forecast day) blocks."""
    if yearly:
        starts = [dt.date(y, 1, 1) for y in range(start.year, end.year + 1)]
    else:
        starts = month_starts(start, end)
    out = []
    for i, r in enumerate(starts):
        nxt = starts[i + 1] - dt.timedelta(days=1) if i + 1 < len(starts) else end
        out.append((r, max(r, start), min(nxt, end)))
    return out


class Runner:
    def __init__(self, f: pd.DataFrame) -> None:
        self.f = f
        self.y = relative_target(f)
        self._x: dict[tuple[str, str], pd.DataFrame] = {}
        self.last_models: dict[str, Any] = {}

    def x(self, day_src: str, ref_src: str) -> pd.DataFrame:
        key = (day_src, ref_src)
        if key not in self._x:
            self._x[key] = design(self.f, day_src, ref_src)
        return self._x[key]

    def run(
        self,
        family: str,
        window: str,
        source: str,
        start: dt.date,
        end: dt.date,
        yearly: bool = False,
    ) -> pd.Series:
        """Forecast (MWh) for every day in [start, end] with forecastable inputs."""
        tr_day, tr_ref, ev_day, ev_ref = SOURCES[source]
        xt, xe = self.x(tr_day, tr_ref), self.x(ev_day, ev_ref)
        dates = np.array(self.f.index)
        years = WINDOWS[window]
        preds = []
        for r, a, b in origins(start, end, yearly):
            last = definitive_available_until(r)
            nxt = last + dt.timedelta(days=1)
            first = nxt.replace(year=nxt.year - years) if years else dates[0]
            tmask = (dates >= first) & (dates <= last)
            tmask &= self.y.notna().to_numpy() & xt["d_t"].notna().to_numpy()
            emask = (dates >= a) & (dates <= b)
            emask &= self.f["ref_mwh"].notna().to_numpy() & xe["d_t"].notna().to_numpy()
            if not emask.any():
                continue
            model = FAMILIES[family]().fit(xt[tmask], self.y[tmask])
            yhat = model.predict(xe[emask])
            ref = self.f.loc[emask, "ref_mwh"]
            preds.append(pd.Series(ref.to_numpy() * np.exp(yhat), index=ref.index))
            self.last_models[f"{family}-{window}-{source}"] = model
        return pd.concat(preds).rename(f"{family}_{window}_{source}")


def abs_pct(pred: pd.Series, actual: pd.Series) -> pd.Series:
    return pct_error(pred, actual).abs()


def compare(
    preds: dict[str, pd.Series], f: pd.DataFrame, baseline: str = "B0"
) -> dict[str, Any]:
    """Scores on the days every forecast covers, bootstrap CIs and residual checks."""
    actual = f["target_mwh"]
    common = pd.concat(preds, axis=1).dropna().index
    out: dict[str, Any] = {"common_days": len(common), "scores": {}, "ci95": {}}
    ape = {k: abs_pct(p.loc[common], actual.loc[common]) for k, p in preds.items()}
    err = {k: (p.loc[common] - actual.loc[common]).abs() for k, p in preds.items()}
    for k, p in preds.items():
        out["scores"][k] = scores(p.loc[common], actual.loc[common])
        mape_ci = block_bootstrap_ci(ape[k].to_frame(), lambda a: a[:, 0].mean())
        ci: dict[str, Any] = {"mape_pct": mape_ci}
        if k != baseline and baseline in preds:
            both = pd.concat([err[k], err[baseline]], axis=1)
            ci["skill_vs_" + baseline] = block_bootstrap_ci(
                both, lambda a: 1 - a[:, 0].mean() / a[:, 1].mean()
            )
            out["scores"][k]["skill_vs_" + baseline] = round(
                float(1 - err[k].mean() / err[baseline].mean()), 4
            )
        out["ci95"][k] = ci
    out["residual_autocorrelation"] = {
        k: acf_ljung_box(pct_error(p.loc[common], actual.loc[common]))
        for k, p in preds.items()
        if not k.startswith("B")
    }
    return out


def baselines(f: pd.DataFrame) -> dict[str, pd.Series]:
    return {"B0": f["ref_mwh"], "B1": f["b1_total_mwh"]}


def out_of_range(f: pd.DataFrame) -> pd.DataFrame:
    """Hot (and, reported only, cold) days vs the same month of all previous years."""
    w = pd.DataFrame(
        {
            "t": f["t_era5"],
            "d_cdd22": f["cdd22_era5"] - f["ref_cdd22_era5"],
            "year": [d.year for d in f.index],
            "month": [d.month for d in f.index],
        },
        index=f.index,
    )
    flags = pd.DataFrame(False, index=f.index, columns=["hot_t", "hot_dcdd", "cold_t"])
    for year in sorted(w["year"].unique()):
        past = w[w["year"] < year]
        if past.empty:
            continue
        now = w["year"] == year
        for m, g in past.groupby("month"):
            sel = now & (w["month"] == m)
            flags.loc[sel, "hot_t"] = w.loc[sel, "t"] > g["t"].quantile(0.99)
            flags.loc[sel, "hot_dcdd"] = w.loc[sel, "d_cdd22"] > g["d_cdd22"].quantile(
                0.99
            )
            flags.loc[sel, "cold_t"] = w.loc[sel, "t"] < g["t"].quantile(0.01)
    flags["out_of_range"] = flags["hot_t"] | flags["hot_dcdd"]
    return flags


def save(name: str, result: dict[str, Any], preds: dict[str, pd.Series]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2, default=str)
    (OUT / f"{name}.json").write_text(text + "\n", encoding="utf-8")
    (INTERIM / "backtest").mkdir(parents=True, exist_ok=True)
    pd.concat(preds, axis=1).to_parquet(INTERIM / "backtest" / f"{name}.parquet")
    print(text)


def read_step(name: str) -> dict[str, Any]:
    return json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))


def step_family(run: Runner, f: pd.DataFrame) -> None:
    val = {
        fam: run.run(fam, "all", "obs", VAL_START, VAL_END) for fam in ("tree", "hyb")
    }
    oracle = {
        f"{fam}_oracle": run.run(fam, "all", "oracle", VAL_START, VAL_END)
        for fam in ("tree", "hyb")
    }
    vf = f.loc[[VAL_START <= d <= VAL_END for d in f.index]]
    preds = {**val, **baselines(vf)}
    result: dict[str, Any] = {"period": [VAL_START, VAL_END]}
    result["validation"] = compare({**val, "B0": vf["ref_mwh"]}, vf)
    result["validation_vs_B1"] = compare({**val, **baselines(vf)}, vf)
    actual = f["target_mwh"]
    dm = diebold_mariano(
        abs_pct(val["hyb"], actual), abs_pct(val["tree"], actual), alternative="greater"
    )
    result["dm_hyb_worse_than_tree"] = dm
    result["oracle_era5_inputs_upper_bound"] = {
        k: scores(p, actual.loc[p.index]) for k, p in oracle.items()
    }
    hyb = run.last_models["hyb-all-obs"]
    assert isinstance(hyb, HybridModel)
    result["hyb_linear_part_last_refit"] = {
        "coef_per_degree_day": dict(
            zip(hyb.linear_cols, [round(float(c), 5) for c in hyb.coef], strict=True)
        ),
        "intercept": round(hyb.intercept, 5),
    }

    ext = {
        fam: run.run(fam, "all", "obs", EXT_START, EXT_END, yearly=True)
        for fam in ("tree", "hyb")
    }
    flags = out_of_range(f)
    common = pd.concat(ext, axis=1).dropna().index
    fl = flags.loc[common]
    ext_res: dict[str, Any] = {
        "period_with_forecast_inputs": [min(common), max(common)],
        "days": len(common),
        "out_of_range_days": int(fl["out_of_range"].sum()),
        "out_of_range_days_per_year": fl.groupby([d.year for d in fl.index])[
            "out_of_range"
        ]
        .sum()
        .astype(int)
        .to_dict(),
        "hot_t_days": int(fl["hot_t"].sum()),
        "hot_dcdd_days": int(fl["hot_dcdd"].sum()),
    }
    for name, sel in (
        ("all_days", fl.index),
        ("out_of_range", fl.index[fl["out_of_range"]]),
        ("in_range", fl.index[~fl["out_of_range"]]),
        ("cold_reported_only", fl.index[fl["cold_t"]]),
    ):
        ext_res[name] = {k: scores(p.loc[sel], actual.loc[sel]) for k, p in ext.items()}
    oor = fl.index[fl["out_of_range"]]
    if len(oor) >= 2 * 7:
        ape = pd.concat(
            [
                abs_pct(ext["hyb"].loc[oor], actual.loc[oor]),
                abs_pct(ext["tree"].loc[oor], actual.loc[oor]),
            ],
            axis=1,
        )
        ext_res["out_of_range_mape_difference_hyb_minus_tree_ci95"] = (
            block_bootstrap_ci(ape, lambda a: a[:, 0].mean() - a[:, 1].mean())
        )
    result["extremes_backtest"] = ext_res

    hyb_mape = ext_res["out_of_range"]["hyb"]["mape_pct"]
    tree_mape = ext_res["out_of_range"]["tree"]["mape_pct"]
    rule_a = float(dm["p_value"]) >= 0.05
    rule_b = hyb_mape < tree_mape
    result["decision"] = {
        "rule_a_hyb_not_worse_on_validation": bool(rule_a),
        "rule_b_hyb_better_out_of_range": bool(rule_b),
        "family": "hyb" if rule_a and rule_b else "tree",
    }
    preds.update({f"ext_{k}": v for k, v in ext.items()})
    preds.update(oracle)
    save("step1_family", result, preds)


def step_window(run: Runner, f: pd.DataFrame) -> None:
    family = read_step("step1_family")["decision"]["family"]
    vf = f.loc[[VAL_START <= d <= VAL_END for d in f.index]]
    val = {w: run.run(family, w, "obs", VAL_START, VAL_END) for w in WINDOWS}
    result: dict[str, Any] = {"family": family}
    result["validation"] = compare({**val, "B0": vf["ref_mwh"]}, vf)
    ranked = sorted(
        WINDOWS, key=lambda w: result["validation"]["scores"][w]["mape_pct"]
    )
    actual = f["target_mwh"]
    result["dm_best_vs_runner_up"] = diebold_mariano(
        abs_pct(val[ranked[0]], actual),
        abs_pct(val[ranked[1]], actual),
        alternative="two-sided",
    )
    result["decision"] = {"window": ranked[0], "ranking": ranked}
    save("step2_window", result, val)


def step_weather(run: Runner, f: pd.DataFrame) -> None:
    family = read_step("step1_family")["decision"]["family"]
    window = read_step("step2_window")["decision"]["window"]
    vf = f.loc[[VAL_START <= d <= VAL_END for d in f.index]]
    val = {s: run.run(family, window, s, VAL_START, VAL_END) for s in ("obs", "fc")}
    result: dict[str, Any] = {"family": family, "window": window}
    result["validation"] = compare({**val, "B0": vf["ref_mwh"]}, vf)
    result["validation_vs_B1"] = compare({**val, **baselines(vf)}, vf)
    actual = f["target_mwh"]
    ranked = sorted(val, key=lambda s: result["validation"]["scores"][s]["mape_pct"])
    result["dm_best_vs_runner_up"] = diebold_mariano(
        abs_pct(val[ranked[0]], actual),
        abs_pct(val[ranked[1]], actual),
        alternative="two-sided",
    )
    result["decision"] = {"weather_source": ranked[0], "ranking": ranked}
    save("step3_weather", result, val)


STEPS = {"family": step_family, "window": step_window, "weather": step_weather}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--step", choices=list(STEPS), required=True)
    args = p.parse_args()
    f = load()
    STEPS[args.step](Runner(f), f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
