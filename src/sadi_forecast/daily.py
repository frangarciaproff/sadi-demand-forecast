"""Daily national demand: weekly area table (D5) and day-ahead programme (B1, D6)."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sadi_forecast.config import N_AREAS


def national_by_version(d5: pd.DataFrame) -> pd.DataFrame:
    """Sum of the 9 areas per (version, date).

    energy_mwh is NaN unless all areas are present and none is missing.
    """
    grp = d5.groupby(["doc_id", "pub_date", "pub_time", "date"])
    out = grp.agg(
        energy_mwh=("energy_mwh", "sum"),
        n_areas=("area", "nunique"),
        n_missing=("missing", "sum"),
    ).reset_index()
    complete = (out["n_areas"] == N_AREAS) & (out["n_missing"] == 0)
    out.loc[~complete, "energy_mwh"] = float("nan")
    return out


def first_and_last(nat: pd.DataFrame) -> pd.DataFrame:
    """Per date: energy in the first and in the last complete published version."""
    ok = nat.dropna(subset=["energy_mwh"])
    ok = ok.sort_values(["date", "pub_date", "pub_time", "doc_id"])
    # head/tail keep whole rows; groupby().first()/last() would mix columns of
    # different versions when some values are null.
    first = ok.groupby("date").head(1).set_index("date")[["energy_mwh", "pub_date"]]
    last = ok.groupby("date").tail(1).set_index("date")[["energy_mwh", "pub_date"]]
    return first.add_suffix("_first").join(last.add_suffix("_last")).reset_index()


def daily_national(d5: pd.DataFrame) -> pd.Series:
    """Latest complete version per date (definitive values when available), MWh."""
    days = first_and_last(national_by_version(d5))
    series = days.set_index("date")["energy_mwh_last"].sort_index()
    series.index = pd.DatetimeIndex(series.index)
    return series.rename("energy_mwh")


# B1 source switch (DECISIONS 2026-10-25): BALANCE.csv from this target day on.
B1_CSV_FROM = dt.date(2024, 11, 13)


def b1_daily(programme: pd.DataFrame) -> pd.DataFrame:
    """B1 per target day: last D6 version published before 00:00 ART on that day.

    Source format by B1_CSV_FROM; if the preferred format is absent, the other one.
    Columns: target_date, energy_mwh (net demand), source, doc_id and, when present,
    b1_total_mwh (net + losses + pumping) and exports_mwh.
    """
    p = programme.dropna(subset=["energy_mwh"]).copy()
    p["pub_date"] = pd.to_datetime(p["pub_date"]).dt.date
    p["target_date"] = pd.to_datetime(p["target_date"]).dt.date
    p = p[p["pub_date"] < p["target_date"]]
    preferred = p["target_date"].map(lambda d: "csv" if d >= B1_CSV_FROM else "txt")
    p["rank_source"] = (p["source"] == preferred).astype(int)
    p = p.sort_values(["target_date", "rank_source", "pub_date", "pub_time", "doc_id"])
    out = p.groupby("target_date").tail(1).reset_index(drop=True)
    cols = ["target_date", "energy_mwh", "source", "doc_id"]
    extra = [c for c in ("b1_total_mwh", "exports_mwh") if c in out.columns]
    return out[cols + extra]
