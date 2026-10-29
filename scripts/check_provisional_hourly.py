"""Provisional vs definitive hourly actual (audit 2026-10-29, v2).

Live hourly scores use, until the monthly balance, the provisional hourly actual: the
latest valid Post Operativo version (s01..s24) minus the programmed hourly exports (D6).
This measures, on data up to 2025-09-30 (no test-year data), against the definitive
hourly actual (D7 supply - D7 exports, latest base):
- each valid version kind (first valid daily report of a day, latest daily report,
  complement): absolute hourly error, daily mean absolute hourly error, peak error,
  peak-hour mismatch;
- the export part alone: programmed vs D7 hourly exports, as % of the hourly actual;
- hour alignment of the programme (D6 t01..t24) with D7: mean absolute share
  difference for shifts of -1, 0 and +1 hour.

Writes results/checks/provisional_hourly.json.

Usage:
    uv run python scripts/check_provisional_hourly.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sadi_forecast.config import EDA_CUTOFF
from sadi_forecast.daily import b1_daily
from sadi_forecast.features import valid_versions
from sadi_forecast.hourly import (
    HOURS,
    S_COLS,
    T_COLS,
    X_COLS,
    definitive_hourly,
    programme_hourly,
)

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _q(x: np.ndarray) -> dict[str, float]:
    x = x[np.isfinite(x)]
    return {
        "median": round(float(np.median(x)), 3),
        "p90": round(float(np.quantile(x, 0.9)), 3),
        "p99": round(float(np.quantile(x, 0.99)), 3),
        "max": round(float(np.max(x)), 3),
    }


def compare(prov: pd.DataFrame, actual: pd.DataFrame) -> dict[str, Any]:
    days = prov.index.intersection(actual.index)
    p, a = prov.loc[days, HOURS].to_numpy(), actual.loc[days, HOURS].to_numpy()
    e = 100 * (p / a - 1)
    peak = 100 * (p.max(axis=1) / a.max(axis=1) - 1)
    hour_diff = np.abs(p.argmax(axis=1) - a.argmax(axis=1))
    return {
        "days": len(days),
        "abs_hourly_error_pct": _q(np.abs(e).ravel()),
        "daily_mean_abs_hourly_error_pct": _q(np.abs(e).mean(axis=1)),
        "abs_peak_error_pct": _q(np.abs(peak)),
        "peak_hour_differs_share": round(float((hour_diff > 0).mean()), 4),
        "peak_hour_off_by_more_than_1h_share": round(float((hour_diff > 1).mean()), 4),
    }


def main() -> int:
    postop = _dates(pd.read_parquet(INTERIM / "d8_postop_versions.parquet"))
    postop = postop[[d <= EDA_CUTOFF for d in postop["date"]]]
    supply = _dates(pd.read_parquet(INTERIM / "d7_supply_hourly.parquet"))
    supply = supply[[d <= EDA_CUTOFF for d in supply["date"]]]
    programme = pd.read_parquet(INTERIM / "d6_programme_hourly.parquet")
    prog = programme_hourly(programme)
    prog = prog[[d <= EDA_CUTOFF for d in prog.index]]
    actual = definitive_hourly(supply)

    v = valid_versions(postop, b1_daily(programme))
    v = v[v["valid"]].sort_values("published_art")
    exports = prog.reindex(v["date"])[X_COLS].fillna(0.0).to_numpy()
    hourly = pd.DataFrame(
        v[S_COLS].to_numpy(dtype=float) - exports, columns=HOURS, index=v.index
    )
    hourly["date"], hourly["kind"] = v["date"].to_numpy(), v["kind"].to_numpy()
    daily = hourly[hourly["kind"] == "daily"]
    groups = {
        "first_valid_daily_report": daily.groupby("date").head(1),
        "latest_valid_daily_report": daily.groupby("date").tail(1),
        "complement": hourly[hourly["kind"] == "complement"].groupby("date").tail(1),
    }
    out: dict[str, Any] = {"period_end": EDA_CUTOFF}
    for name, g in groups.items():
        out[name] = compare(g.set_index("date")[HOURS], actual)

    # Export part alone: programmed vs D7 exports, in % of the definitive hourly actual.
    s = supply.copy()
    counts = s.groupby(["base", "date"])["hour"].nunique()
    full = counts[counts == 24].reset_index()[["base", "date"]]
    latest = full.sort_values(["date", "base"]).groupby("date").tail(1)
    s = s.merge(latest, on=["base", "date"])
    exp7 = s.pivot(index="date", columns="hour", values="export_mwh")[HOURS]
    days = exp7.index.intersection(prog.index).intersection(actual.index)
    x_prog = prog.loc[days, X_COLS].fillna(0.0).to_numpy()
    diff = (
        100 * np.abs(x_prog - exp7.loc[days].to_numpy()) / actual.loc[days].to_numpy()
    )
    export_days = (exp7.loc[days].fillna(0.0).sum(axis=1) > 0).to_numpy()
    out["exports_programmed_vs_d7_pct_of_hourly_actual"] = {
        "days": len(days),
        "days_with_exports": int(export_days.sum()),
        "hours_without_d7_exports": int(np.isnan(diff).sum()),
        "all_hours": _q(diff.ravel()),
        "hours_on_export_days": _q(diff[export_days].ravel()),
    }

    # Hour alignment of the programme with D7 (shares, so the level does not matter).
    days = prog.index.intersection(actual.index)
    t = prog.loc[days, T_COLS].dropna()
    ts = t.to_numpy() / t.to_numpy().sum(axis=1, keepdims=True)
    a = actual.loc[t.index].to_numpy()
    av = a / a.sum(axis=1, keepdims=True)
    shifts = {}
    for k in (-1, 0, 1):
        lo, hi = max(0, k), 24 + min(0, k)
        d = np.abs(ts[:, lo:hi] - av[:, lo - k : hi - k])
        shifts[str(k)] = round(float(100 * d.mean() * 24), 4)
    # Half-hour shifts: D7 hour h ((h-1):00-h:00) against the mean of programme hours
    # h-1 and h (programme hour h centred on h:00) or h and h+1, hours 2..23.
    mid = av[:, 1:-1]
    half = {
        "as_published": float(np.abs(ts[:, 1:-1] - mid).mean()),
        "d7_h_vs_mean_programme_h-1_h": float(
            np.abs((ts[:, :-2] + ts[:, 1:-1]) / 2 - mid).mean()
        ),
        "d7_h_vs_mean_programme_h_h+1": float(
            np.abs((ts[:, 1:-1] + ts[:, 2:]) / 2 - mid).mean()
        ),
    }
    out["programme_hour_alignment_mean_abs_share_diff_pct"] = {
        "days": len(t),
        "note": "shift k compares programme hour h with D7 hour h - k; 0 should be "
        "smallest. Values x24 (relative to an average hour).",
        "by_shift": shifts,
        "half_hour": {k: round(100 * v * 24, 4) for k, v in half.items()},
    }
    folder = ROOT / "results" / "checks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "provisional_hourly.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
