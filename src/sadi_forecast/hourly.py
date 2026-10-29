"""v2: hourly curve (T3) and daily peak (T2), SPEC 11.

Forecast of hour h of day D = v1 daily energy x share s(D, h), with sum_h s = 1.
- Shares of a Post Operativo version: (hourly supply - programmed hourly exports) / day
  total.
- S0(D): median share per hour over the reference days D-7...D-28, each in its latest
  valid version published before the issue time (the same versions as v1's reference
  level), at least two days, renormalised.
- S1: trees on ln(s / s0) per (day, hour) with hour, calendar and hourly temperature.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from sadi_forecast.daily import b1_daily
from sadi_forecast.features import REF_LAGS, REF_MIN, issue_time
from sadi_forecast.models import CATEGORICAL, KINDS, TREE_PARAMS

HOURS = list(range(1, 25))
S_COLS = [f"s{h:02d}" for h in HOURS]
T_COLS = [f"t{h:02d}" for h in HOURS]
X_COLS = [f"x{h:02d}" for h in HOURS]


def definitive_hourly(supply: pd.DataFrame) -> pd.DataFrame:
    """D7 hourly supply - exports (date x hour 1..24), latest base with all 24 hours."""
    s = supply.dropna(subset=["supply_mwh", "export_mwh"])
    counts = s.groupby(["base", "date"])["hour"].nunique()
    full = counts[counts == 24].reset_index()[["base", "date"]]
    latest = full.sort_values(["date", "base"]).groupby("date").tail(1)
    s = s.merge(latest, on=["base", "date"])
    s = s.assign(value=s["supply_mwh"] - s["export_mwh"])
    out = s.pivot(index="date", columns="hour", values="value")
    out.columns = [int(c) for c in out.columns]
    return out[HOURS]


def programme_hourly(programme: pd.DataFrame) -> pd.DataFrame:
    """Hourly B1 total (t01..t24) and programmed exports (x01..x24) of the version
    b1_daily selects for each target day."""
    chosen = b1_daily(programme)[["target_date", "doc_id", "source"]]
    p = programme.copy()
    p["target_date"] = pd.to_datetime(p["target_date"]).dt.date
    p = p.merge(chosen, on=["target_date", "doc_id", "source"])
    p = p.drop_duplicates(subset=["target_date"], keep="last").set_index("target_date")
    return p[T_COLS + X_COLS]


def version_shapes(versions: pd.DataFrame, prog: pd.DataFrame) -> pd.DataFrame:
    """Hourly shares of every valid Post Operativo version (rows as in versions)."""
    v = versions[versions["valid"]].copy()
    exports = prog.reindex(v["date"])[X_COLS].fillna(0.0).to_numpy()
    hourly = v[S_COLS].to_numpy(dtype=float) - exports
    total = hourly.sum(axis=1, keepdims=True)
    shares = np.where(total > 0, hourly / np.where(total > 0, total, 1.0), np.nan)
    out = pd.DataFrame(shares, columns=HOURS, index=v.index)
    out["date"] = v["date"].to_numpy()
    out["published_art"] = v["published_art"].to_numpy()
    return out.dropna(subset=HOURS)


def reference_shapes(
    shapes: pd.DataFrame, days: list[dt.date]
) -> tuple[pd.DataFrame, dict[dt.date, list[dt.date]]]:
    """S0 per target day and the reference days it used."""
    by_date = {d: g.sort_values("published_art") for d, g in shapes.groupby("date")}
    rows, used = {}, {}
    for day in days:
        t = issue_time(day)
        picked, refs = [], []
        for k in REF_LAGS:
            r = day - dt.timedelta(days=k)
            g = by_date.get(r)
            if g is None:
                continue
            known = g[g["published_art"] < t]
            if not known.empty:
                picked.append(known[HOURS].iloc[-1].to_numpy(dtype=float))
                refs.append(r)
        if len(picked) >= REF_MIN:
            med = np.median(np.vstack(picked), axis=0)
            rows[day] = med / med.sum()
            used[day] = refs
    return pd.DataFrame.from_dict(rows, orient="index", columns=HOURS), used


def hourly_temperature(
    hourly: pd.DataFrame, column: str, weights: pd.Series
) -> pd.DataFrame:
    """Demand-weighted temperature at the start of each hour (date x hour 1..24, ART).

    Hour h covers [h - 1, h): its temperature is the value at h - 1. NaN if a point with
    positive weight is missing.
    """
    w = weights[weights > 0]
    h = hourly[["point", "time_art", column]].dropna()
    wide = h.pivot_table(index="time_art", columns="point", values=column)
    wide = wide.reindex(columns=w.index)
    temp = wide.mul(w, axis=1).sum(axis=1).where(wide.notna().all(axis=1))
    times = pd.DatetimeIndex(temp.index)
    frame = pd.DataFrame(
        {"date": times.date, "hour": times.hour + 1, "t": temp.to_numpy()}
    )
    out = frame.pivot_table(index="date", columns="hour", values="t", dropna=False)
    out.columns = [int(c) for c in out.columns]
    return out.reindex(columns=HOURS)


def design_hourly(
    f: pd.DataFrame,
    s0: pd.DataFrame,
    temp: pd.DataFrame,
    used: dict[dt.date, list[dt.date]],
    days: list[dt.date],
) -> pd.DataFrame:
    """One row per (day, hour) for the days with S0 and a complete temperature day."""
    recs = []
    for d in days:
        if d not in s0.index or d not in temp.index or d not in f.index:
            continue
        td = temp.loc[d]
        if td.isna().any():
            continue
        refs = [r for r in used[d] if r in temp.index and not temp.loc[r].isna().any()]
        tref = temp.loc[refs].mean() if refs else pd.Series(math.nan, index=HOURS)
        row = f.loc[d]
        for h in HOURS:
            recs.append(
                {
                    "date": d,
                    "hour": h,
                    "dow": row["dow"],
                    "day_kind": row["day_kind"],
                    "prev_day_kind": row["prev_day_kind"],
                    "next_day_kind": row["next_day_kind"],
                    "doy_sin": row["doy_sin"],
                    "doy_cos": row["doy_cos"],
                    "t_hour": td[h],
                    "d_t_hour": td[h] - tref[h],
                    "d_t_day": row["t_gfs"] - row["ref_t_gfs"],
                    "s0": s0.at[d, h],
                }
            )
    x = pd.DataFrame(recs)
    for c in CATEGORICAL:
        x[c] = pd.Categorical(x[c].fillna(""), categories=KINDS)
    return x


FEATURES = [
    "hour",
    "dow",
    "day_kind",
    "prev_day_kind",
    "next_day_kind",
    "doy_sin",
    "doy_cos",
    "t_hour",
    "d_t_hour",
    "d_t_day",
]


def shape_target(x: pd.DataFrame, actual: pd.DataFrame) -> pd.Series:
    """ln(actual share / s0) for the rows of x (NaN where the day has no actual)."""
    share = actual.div(actual.sum(axis=1), axis=0)
    vals = [
        share.at[d, h] if d in share.index else math.nan
        for d, h in zip(x["date"], x["hour"], strict=True)
    ]
    return pd.Series(
        np.log(np.array(vals, dtype=float) / x["s0"].to_numpy()), index=x.index
    )


def shares_from_model(x: pd.DataFrame, pred: np.ndarray) -> pd.DataFrame:
    """Renormalised S1 shares (day x hour) from ln(s / s0) predictions."""
    raw = x[["date", "hour"]].assign(v=x["s0"].to_numpy() * np.exp(pred))
    wide = raw.pivot(index="date", columns="hour", values="v")
    return wide.div(wide.sum(axis=1), axis=0)


TREES = dict(TREE_PARAMS)


def align_programme(prog: pd.DataFrame) -> pd.DataFrame:
    """The operator's hourly programme (T_COLS) on D7's hours (DECISIONS 2026-10-29).

    The programme's hour h is centred on h:00, D7's hour h covers (h-1):00..h:00, so
    the aligned value of hour h is the mean of programme hours h-1 and h; hour 1 uses
    hour 24 of the previous day (hour 1 itself if that day is missing). Returns a
    date x hour 1..24 frame.
    """
    t = prog[T_COLS].astype(float).copy()
    t.columns = HOURS
    idx = pd.Index(t.index)
    prev_day = [d - dt.timedelta(days=1) for d in idx]
    prev24 = t[24].reindex(prev_day).to_numpy()
    first = np.where(np.isnan(prev24), t[1].to_numpy(), prev24)
    vals = t.to_numpy()
    out = np.empty_like(vals)
    out[:, 0] = (first + vals[:, 0]) / 2
    out[:, 1:] = (vals[:, :-1] + vals[:, 1:]) / 2
    return pd.DataFrame(out, index=t.index, columns=HOURS)
