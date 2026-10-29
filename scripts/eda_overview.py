"""EDA figures for daily national demand (data up to 2025-09-30 only; SPEC 4.1).

Source: D5 national net demand, latest complete version per day (sum of 9 areas).
D1 gross energy is drawn as a reference in the per-year figures.

Outputs (committed; derived plots are allowed by CAMMESA; no raw values stored):
    results/eda/figures/daily_by_year/daily_YYYY.png   one figure per year
    results/eda/figures/daily_all_years.png            full series with rolling means
    results/eda/figures/seasonal_overlay.png           all years on a day-of-year axis
    results/eda/figures/monthly_mean.png               monthly mean of daily energy
    results/eda/figures/monthly_yoy.png                year-over-year change by month
    results/eda/figures/monthly_coverage.png           complete days per month
    results/eda/figures/covid_profiles.png             weekly and seasonal profiles,
                                                       2017-19 vs 2022-24
    results/eda/covid_summary.json                     same comparison, bootstrap CIs

Usage (from the repository root):
    uv run python scripts/eda_overview.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from sadi_forecast.config import EDA_CUTOFF
from sadi_forecast.daily import daily_national

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "results" / "eda"
FIG = OUT / "figures"

# Reference palette (dataviz skill, light mode)
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
BLUE_RAMP = [
    "#cde2fb",
    "#9ec5f4",
    "#6da7ec",
    "#3987e5",
    "#256abf",
    "#184f95",
    "#0d366b",
]
NEUTRAL = "#f0efec"
RED = "#e34948"

PRE = (dt.date(2017, 1, 1), dt.date(2019, 12, 31))
POST = (dt.date(2022, 1, 1), dt.date(2024, 12, 31))
LOCKDOWN = dt.date(2020, 3, 20)
N_BOOT = 2000
SEED = 20261025


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": TEXT_2,
            "axes.titlecolor": TEXT,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": TEXT_2,
            "ytick.color": TEXT_2,
            "legend.frameon": False,
            "legend.labelcolor": TEXT_2,
            "font.size": 9,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def load() -> tuple[pd.Series, pd.Series]:
    d5 = pd.read_parquet(INTERIM / "d5_area_hourly.parquet")
    d5 = d5[d5["date"] <= EDA_CUTOFF]
    net = daily_national(d5) / 1000  # GWh/day
    d1 = pd.read_parquet(INTERIM / "d1_daily.parquet")
    d1 = d1[d1["date"] <= EDA_CUTOFF]
    gross = pd.Series(
        d1["gross_energy_mwh"].to_numpy() / 1000, index=pd.DatetimeIndex(d1["date"])
    ).sort_index()
    return net, gross


def per_year(net: pd.Series, gross: pd.Series) -> None:
    full = net.asfreq("D")  # missing days become gaps in the line
    for year in sorted(set(pd.DatetimeIndex(net.index).year)):
        fig, ax = plt.subplots(figsize=(10, 3.2))
        g = gross[pd.DatetimeIndex(gross.index).year == year].asfreq("D")
        n = full[pd.DatetimeIndex(full.index).year == year]
        if len(g.dropna()):
            ax.plot(
                g.index,
                g.to_numpy(),
                color=ORANGE,
                lw=1.2,
                label="Gross (D1, reference)",
            )
        ax.plot(
            n.index, n.to_numpy(), color=BLUE, lw=1.5, label="Net (D5, sum of areas)"
        )
        ax.set_title(f"Daily electricity demand, SADI, {year}")
        ax.set_ylabel("GWh/day")
        ax.legend(loc="upper left", ncols=2)
        save(fig, FIG / "daily_by_year" / f"daily_{year}.png")


def all_years(net: pd.Series) -> None:
    full = net.asfreq("D")
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(full.index, full.to_numpy(), color=BLUE_RAMP[1], lw=0.6, label="Daily")
    ax.plot(
        full.index,
        full.rolling(28, min_periods=20).mean().to_numpy(),
        color=BLUE,
        lw=1.5,
        label="28-day mean",
    )
    ax.plot(
        full.index,
        full.rolling(365, min_periods=300).mean().to_numpy(),
        color=BLUE_RAMP[6],
        lw=2,
        label="365-day mean",
    )
    ax.axvline(float(mdates.date2num(LOCKDOWN)), color=AXIS, lw=1, ls="--")
    ax.text(
        float(mdates.date2num(LOCKDOWN)),
        ax.get_ylim()[1],
        " lockdown 2020-03-20",
        color=TEXT_2,
        va="top",
        fontsize=8,
    )
    ax.set_title("Daily net demand, SADI, 2010 to 2025-09 (D5)")
    ax.set_ylabel("GWh/day")
    ax.legend(loc="upper left", ncols=3)
    save(fig, FIG / "daily_all_years.png")


def seasonal_overlay(net: pd.Series) -> None:
    years = sorted(set(pd.DatetimeIndex(net.index).year))
    cmap = LinearSegmentedColormap.from_list("seq", BLUE_RAMP)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    for i, year in enumerate(years):
        s = (
            net[pd.DatetimeIndex(net.index).year == year]
            .asfreq("D")
            .rolling(7, min_periods=5, center=True)
            .mean()
        )
        color = cmap(i / max(len(years) - 1, 1))
        doy = pd.DatetimeIndex(s.index).day_of_year
        ax.plot(doy, s.to_numpy(), color=color, lw=1.2)
        if year in (years[0], years[-1]):
            last = s.dropna()
            ax.annotate(
                str(year),
                (last.index[-1].day_of_year, last.iloc[-1]),
                color=TEXT_2,
                fontsize=8,
                xytext=(3, 0),
                textcoords="offset points",
                va="center",
            )
    ax.set_xticks([1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335])
    ax.set_xticklabels(
        [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
    )
    sm = plt.cm.ScalarMappable(
        cmap=cmap, norm=mpl.colors.Normalize(years[0], years[-1])
    )
    cb = fig.colorbar(sm, ax=ax, pad=0.01, aspect=30)
    cb.set_label("Year", color=TEXT_2)
    cb.outline.set_visible(False)
    ax.set_title("Seasonal profile by year, 7-day centred mean (lighter = older)")
    ax.set_ylabel("GWh/day")
    save(fig, FIG / "seasonal_overlay.png")


def monthly(net: pd.Series) -> None:
    by_month = net.groupby(
        [pd.DatetimeIndex(net.index).year, pd.DatetimeIndex(net.index).month]
    )
    mean = by_month.mean().rename_axis(["year", "month"])
    count = by_month.size().rename_axis(["year", "month"])
    stamp = pd.to_datetime(
        {
            "year": mean.index.get_level_values(0),
            "month": mean.index.get_level_values(1),
            "day": 15,
        }
    )
    fig, ax = plt.subplots(figsize=(12, 3.6))
    ax.plot(stamp, mean.to_numpy(), color=BLUE, lw=1.5, marker="o", ms=3)
    ax.set_title("Monthly mean of daily net demand (D5)")
    ax.set_ylabel("GWh/day")
    save(fig, FIG / "monthly_mean.png")

    grid = mean.unstack("month")
    yoy = 100 * (grid / grid.shift(1) - 1)
    lim = float(np.nanpercentile(np.abs(yoy.to_numpy()), 98))
    cmap = LinearSegmentedColormap.from_list("div", [BLUE, NEUTRAL, RED])
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(yoy.to_numpy(), cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
    for (r, c), v in np.ndenumerate(yoy.to_numpy()):
        if np.isfinite(v):
            ax.text(c, r, f"{v:+.0f}", ha="center", va="center", fontsize=7, color=TEXT)
    ax.set_xticks(
        range(12), ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    )
    ax.set_yticks(range(len(yoy.index)), [str(y) for y in yoy.index])
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, pad=0.01)
    cb.set_label("% vs same month previous year", color=TEXT_2)
    cb.outline.set_visible(False)
    ax.set_title("Year-over-year change of monthly mean demand (%)")
    save(fig, FIG / "monthly_yoy.png")

    cov = count.unstack("month")
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(
        cov.to_numpy(),
        cmap=LinearSegmentedColormap.from_list("seq", BLUE_RAMP),
        vmin=0,
        vmax=31,
        aspect="auto",
    )
    for (r, c), v in np.ndenumerate(cov.to_numpy()):
        if np.isfinite(v):
            ax.text(
                c,
                r,
                f"{int(v)}",
                ha="center",
                va="center",
                fontsize=7,
                color=TEXT if v < 20 else SURFACE,
            )
    ax.set_xticks(
        range(12), ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    )
    ax.set_yticks(range(len(cov.index)), [str(y) for y in cov.index])
    ax.grid(False)
    ax.set_title("Days with complete data (all 9 areas, no missing rows)")
    save(fig, FIG / "monthly_coverage.png")


def _period(net: pd.Series, span: tuple[dt.date, dt.date]) -> pd.Series:
    return net[
        (net.index >= pd.Timestamp(span[0])) & (net.index <= pd.Timestamp(span[1]))
    ]


def _ratios(s: pd.Series) -> dict[str, float]:
    dow = pd.DatetimeIndex(s.index).day_of_week
    month = pd.DatetimeIndex(s.index).month
    return {
        "mean_gwh_day": float(s.mean()),
        "weekday_weekend_ratio": float(s[dow < 5].mean() / s[dow >= 5].mean()),
        "summer_winter_ratio": float(
            s[np.isin(month, [12, 1, 2])].mean() / s[np.isin(month, [6, 7, 8])].mean()
        ),
    }


def _block_bootstrap(s: pd.Series, rng: np.random.Generator) -> list[dict[str, float]]:
    weeks = [w for _, w in s.groupby(pd.DatetimeIndex(s.index).to_period("W"))]
    out = []
    for _ in range(N_BOOT):
        pick = rng.integers(0, len(weeks), len(weeks))
        out.append(_ratios(pd.concat([weeks[i] for i in pick])))
    return out


def covid(net: pd.Series) -> None:
    pre, post = _period(net, PRE), _period(net, POST)
    rng = np.random.default_rng(SEED)
    boot_pre, boot_post = _block_bootstrap(pre, rng), _block_bootstrap(post, rng)
    summary: dict[str, object] = {
        "pre": f"{PRE[0]} to {PRE[1]}",
        "post": f"{POST[0]} to {POST[1]}",
        "method": "weekly block bootstrap, B=2000, 95% percentile intervals; "
        "no temperature or calendar adjustment (holidays fall inside weekdays)",
        "n_days": {"pre": len(pre), "post": len(post)},
    }
    stats = {}
    for key in _ratios(pre):
        a = np.array([b[key] for b in boot_pre])
        b = np.array([b[key] for b in boot_post])
        diff = b - a
        stats[key] = {
            "pre": round(_ratios(pre)[key], 4),
            "post": round(_ratios(post)[key], 4),
            "post_minus_pre_ci95": [
                round(float(np.percentile(diff, 2.5)), 4),
                round(float(np.percentile(diff, 97.5)), 4),
            ],
        }
    summary["statistics"] = stats
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "covid_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8))
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for s, color, label in ((pre, BLUE, "2017-2019"), (post, ORANGE, "2022-2024")):
        dow = s.groupby(pd.DatetimeIndex(s.index).day_of_week).mean() / s.mean()
        a1.plot(days, dow.to_numpy(), color=color, lw=2, marker="o", ms=5, label=label)
        mon = s.groupby(pd.DatetimeIndex(s.index).month).mean() / s.mean()
        a2.plot(
            range(1, 13),
            mon.to_numpy(),
            color=color,
            lw=2,
            marker="o",
            ms=5,
            label=label,
        )
    a1.set_title("Weekly profile (day mean / period mean)")
    a2.set_title("Seasonal profile (month mean / period mean)")
    a2.set_xticks(
        range(1, 13), ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    )
    for ax, where in ((a1, "lower left"), (a2, "upper center")):
        ax.axhline(1, color=AXIS, lw=0.8)
        ax.legend(loc=where)
    save(fig, FIG / "covid_profiles.png")
    print(json.dumps(summary, indent=2))


def main() -> int:
    style()
    net, gross = load()
    per_year(net, gross)
    all_years(net)
    seasonal_overlay(net)
    monthly(net)
    covid(net)
    print(f"figures written to {FIG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
