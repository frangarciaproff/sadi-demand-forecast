"""Daily feature table: one row per target day D, as known at the issue time.

Issue time: 10:00 ART on D-1 (SPEC 1). Columns:
- target_mwh: definitive supplied energy of D (D7 supply - D7 exports).
- lag_k (k = 3..28): provisional value of day D-k in the latest valid Post
  Operativo version published before the issue time (NaN if none); lag_k_kind
  says which version ("daily" or "complement").
- ref_mwh: reference level = median of the available values among lag_7, lag_14,
  lag_21 and lag_28 (same weekday, previous four weeks; at least 2 needed), robust to
  one wrong daily report (audit 2026-10-29, Fran). ref_n: values used. The reference
  carries its own weather: ref_<weather column> is the mean of that column over the
  same reference days. Version mix: the label is definitive, the reference is the
  provisional version known at the issue time, in training and in production alike.
- calendar: dow, day_kind, prev_day_kind, next_day_kind, off_day, doy_sin/doy_cos,
  trend_days.
- weather, for each source (era5: observed; gfs: forecast issued two days before),
  demand-weighted over the points: t_<src> (weighted daily mean temperature),
  hdd<b>_<src> and cdd<b>_<src> (weighted degree days, computed per point first).
- b1_total_mwh: operator programme for D (benchmark only; published after the
  issue time, never a feature).
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from sadi_forecast.calendar_ar import calendar_features

ART = dt.timezone(dt.timedelta(hours=-3))
ISSUE_HOUR = 10
LAGS = 28
FIRST_LAG = 3  # D-1 and D-2 are never published by 10:00 on D-1
HDD_BASES = (14, 16, 18)
CDD_BASES = (20, 22, 24)
TREND_ORIGIN = dt.date(2018, 1, 1)
REF_LAGS = (7, 14, 21, 28)
REF_MIN = 2
# Validity check of daily reports (SPEC 2.2, O14, Fran 2026-10-28): reject a daily
# report whose provisional value differs from the programme by more than K1, or
# that lacks hours or supply.
K1 = 0.10


def issue_time(day: dt.date) -> dt.datetime:
    """Naive ART timestamp of the forecast issue for target day `day`."""
    return dt.datetime.combine(day - dt.timedelta(days=1), dt.time(ISSUE_HOUR))


def published_art(version: pd.Series) -> pd.Series:
    """Listing version strings (ISO with offset) to naive ART timestamps."""
    ts = pd.to_datetime(version, utc=True, errors="coerce")
    return ts.dt.tz_convert(ART).dt.tz_localize(None)


def valid_versions(postop: pd.DataFrame, b1: pd.DataFrame) -> pd.DataFrame:
    """Every Post Operativo version with its provisional value and validity.

    value = supply - programmed exports of that day. Complements are always valid;
    daily reports must have 24 hours, positive supply and |value / B1 - 1| <= K1
    (the last rule is skipped on the days without a programme).
    """
    prog = b1.set_index("target_date")
    v = postop[postop["kind"].isin(["daily", "complement"])].copy()
    v["published_art"] = published_art(v["published"])
    exports = v["date"].map(prog["exports_mwh"]).fillna(0.0)
    v["value_mwh"] = v["supply_mwh"] - exports
    ratio = v["value_mwh"] / v["date"].map(prog["b1_total_mwh"])
    ok_daily = (
        (v["hours_present"] == 24)
        & (v["supply_mwh"] > 0)
        & (((ratio - 1).abs() <= K1) | ratio.isna())
    )
    v["valid"] = (v["kind"] == "complement") | ok_daily
    return v.dropna(subset=["published_art"])


def lag_table(versions: pd.DataFrame, days: list[dt.date]) -> pd.DataFrame:
    """lag_k for each target day: latest valid version published before issue."""
    ok = versions[versions["valid"]].sort_values("published_art")
    by_date = {d: g for d, g in ok.groupby("date")}
    rows = []
    for day in days:
        t = issue_time(day)
        rec: dict[str, object] = {"date": day}
        for k in range(FIRST_LAG, LAGS + 1):
            g = by_date.get(day - dt.timedelta(days=k))
            value, kind = math.nan, ""
            if g is not None:
                known = g[g["published_art"] < t]
                if not known.empty:
                    value = float(known["value_mwh"].iloc[-1])
                    kind = str(known["kind"].iloc[-1])
            rec[f"lag_{k}"] = value
            rec[f"lag_{k}_kind"] = kind
        rows.append(rec)
    return pd.DataFrame(rows).set_index("date")


def weather_daily(hourly: pd.DataFrame, column: str) -> pd.DataFrame:
    """Daily mean of `column` per point and Argentina day (rows date, cols point)."""
    h = hourly[["point", "time_art", column]].dropna()
    h = h.assign(date=h["time_art"].dt.date)
    counts = h.groupby(["date", "point"])[column].count()
    means = h.groupby(["date", "point"])[column].mean()
    means = means[counts == 24]
    return means.unstack("point")


def weighted_degree_days(
    temp: pd.DataFrame, weights: pd.Series, src: str
) -> pd.DataFrame:
    """Weighted mean temperature and degree days (NaN if a point is missing)."""
    w = weights[weights > 0]
    t = temp.reindex(columns=w.index)
    complete = t.notna().all(axis=1)
    out = pd.DataFrame(index=t.index)
    out[f"t_{src}"] = t.mul(w, axis=1).sum(axis=1)
    for b in HDD_BASES:
        out[f"hdd{b}_{src}"] = (b - t).clip(lower=0).mul(w, axis=1).sum(axis=1)
    for b in CDD_BASES:
        out[f"cdd{b}_{src}"] = (t - b).clip(lower=0).mul(w, axis=1).sum(axis=1)
    out[~complete] = np.nan
    return out


def reference(table: pd.DataFrame, weather_cols: list[str]) -> pd.DataFrame:
    """Median of the same-weekday lags and the mean weather of the days used."""
    lags = table[[f"lag_{k}" for k in REF_LAGS]]
    n = lags.notna().sum(axis=1)
    out = pd.DataFrame(index=table.index)
    out["ref_mwh"] = lags.median(axis=1).where(n >= REF_MIN)
    out["ref_n"] = n
    dates = list(table.index)
    for col in weather_cols:
        series = table[col]
        values = []
        for d, row in zip(dates, lags.itertuples(index=False), strict=True):
            used = [
                series.get(d - dt.timedelta(days=k))
                for k, v in zip(REF_LAGS, row, strict=True)
                if not math.isnan(v)
            ]
            ok = [float(u) for u in used if u is not None and not math.isnan(u)]
            values.append(sum(ok) / len(ok) if len(ok) >= REF_MIN else math.nan)
        out[f"ref_{col}"] = values
    return out


def build_features(
    target: pd.DataFrame,
    versions: pd.DataFrame,
    b1: pd.DataFrame,
    weather: dict[str, pd.DataFrame],
    weights: pd.Series,
    days: list[dt.date],
) -> pd.DataFrame:
    """Assemble the table for `days`.

    weather: source -> daily temperature per point (output of weather_daily).
    """
    out = pd.DataFrame(index=pd.Index(days, name="date"))
    out["target_mwh"] = target.set_index("date")["target_mwh"].reindex(days)
    out = out.join(lag_table(versions, days))
    out = out.join(calendar_features(days))
    doy = np.array([d.timetuple().tm_yday for d in days])
    out["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    out["trend_days"] = [(d - TREND_ORIGIN).days for d in days]
    weather_cols: list[str] = []
    for src, temp in weather.items():
        wdd = weighted_degree_days(temp, weights, src)
        weather_cols += list(wdd.columns)
        out = out.join(wdd)
    out = out.join(reference(out, weather_cols))
    out["b1_total_mwh"] = b1.set_index("target_date")["b1_total_mwh"].reindex(days)
    return out
