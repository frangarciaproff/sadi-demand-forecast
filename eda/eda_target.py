"""EDA figures for the target (supplied energy) and its live sources.

Data up to 2025-09-30 only (EDA rule, SPEC 4.1). Requires build_tables.py
--only d6 d7 d8 and the ERA5 download (scripts/get_weather.py); daily mean
temperature per point (Argentina days) is cached in
data/interim/eda/era5_daily_temp.csv.

Outputs (aggregated plots only, committed in results/eda/figures):
    target_daily.png          daily target, 7- and 365-day means
    target_vs_temperature.png target vs daily mean temperature
    programme_error.png       operator programme vs target
    daily_report_error.png    daily report vs complement

Usage (from the repository root):
    uv run python eda/eda_target.py
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from sadi_forecast.config import EDA_CUTOFF
from sadi_forecast.daily import b1_daily
from sadi_forecast.targets import definitive_daily, provisional_daily

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
FIG = ROOT / "results" / "eda" / "figures"
VALIDATION_START = dt.date(2024, 10, 1)
K1 = 0.10  # validity check threshold (SPEC 2.2, O14)

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
RED = "#e34948"
LIGHT = "#9ec5f4"


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


def save(fig: plt.Figure, name: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / name)
    plt.close(fig)


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    postop = pd.read_parquet(INTERIM / "d8_postop_versions.parquet")
    postop["date"] = pd.to_datetime(postop["date"]).dt.date
    supply = pd.read_parquet(INTERIM / "d7_supply_hourly.parquet")
    supply["date"] = pd.to_datetime(supply["date"]).dt.date
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))
    target = definitive_daily(postop, supply)
    target = target[target["date"] <= EDA_CUTOFF].set_index("date").sort_index()
    prov = provisional_daily(postop, b1)
    prov = prov[prov["date"] <= EDA_CUTOFF].copy()
    prov["supply_dev"] = prov["supply_mwh"] / prov["date"].map(target["supply_mwh"]) - 1
    prov["r1"] = prov["provisional_mwh"] / prov["b1_total_mwh"]
    return target, prov, b1


def target_daily(target: pd.DataFrame) -> None:
    s = (target["target_mwh"] / 1000).dropna()
    s.index = pd.DatetimeIndex(s.index)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(s.index, s, color=LIGHT, lw=0.5, label="Daily")
    ax.plot(s.index, s.rolling(7).mean(), color=BLUE, lw=1.0, label="7-day mean")
    ax.plot(s.index, s.rolling(365).mean(), color=TEXT, lw=1.4, label="365-day mean")
    x_val = float(mdates.date2num(VALIDATION_START))
    ax.axvline(x_val, color=ORANGE, lw=1, ls="--")
    ax.text(
        x_val,
        ax.get_ylim()[1],
        " validation →",
        color=ORANGE,
        va="top",
    )
    ax.set_title("Supplied energy (generation + imports - exports), GWh per day")
    ax.set_ylabel("GWh")
    ax.legend(loc="upper left", ncols=3)
    save(fig, "target_daily.png")


def daily_temperature() -> pd.DataFrame:
    """Daily mean ERA5 2 m temperature per point, Argentina days (UTC-3)."""
    path = INTERIM / "eda" / "era5_daily_temp.csv"
    if not path.exists():
        acc: dict[tuple[str, str], list[float]] = {}
        raw = ROOT / "data" / "raw" / "open_meteo" / "era5"
        for f in sorted(raw.glob("*/*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            point = data["_request"]["point"]["key"]
            hourly = data["hourly"]
            for t, v in zip(hourly["time"], hourly["temperature_2m"], strict=True):
                if v is None:
                    continue
                day = (dt.datetime.fromisoformat(t) - dt.timedelta(hours=3)).date()
                a = acc.setdefault((point, day.isoformat()), [0.0, 0.0])
                a[0] += v
                a[1] += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["point", "date", "tmean", "n"])
            for (p, d), (total, n) in sorted(acc.items()):
                w.writerow([p, d, round(total / n, 3), int(n)])
    return pd.read_csv(path)


def target_vs_temperature(target: pd.DataFrame) -> None:
    temp = daily_temperature()
    temp = temp[temp["point"] == "caba"]
    t = pd.Series(temp["tmean"].to_numpy(), index=pd.to_datetime(temp["date"]).dt.date)
    df = pd.DataFrame({"gwh": target["target_mwh"] / 1000, "temp": t}).dropna()
    df = df[[d < VALIDATION_START for d in df.index]]
    wd = pd.Series([pd.Timestamp(d).day_of_week for d in df.index], index=df.index)
    fig, ax = plt.subplots(figsize=(7, 5))
    for mask, color, label in (
        (wd < 5, BLUE, "Monday-Friday"),
        (wd == 5, ORANGE, "Saturday"),
        (wd == 6, RED, "Sunday"),
    ):
        ax.scatter(
            df.loc[mask, "temp"],
            df.loc[mask, "gwh"],
            s=5,
            alpha=0.5,
            c=color,
            label=label,
            linewidths=0,
        )
    ax.set_title("Supplied energy vs daily mean temperature (Buenos Aires)")
    ax.set_xlabel("Daily mean temperature, °C (ERA5, CABA point)")
    ax.set_ylabel("GWh per day")
    ax.legend(loc="upper center", markerscale=3)
    ax.text(
        0.0,
        -0.15,
        "Training days 2018-01 → 2024-09. Holidays not separated.",
        transform=ax.transAxes,
        color=TEXT_2,
        fontsize=8,
    )
    save(fig, "target_vs_temperature.png")


def programme_error(target: pd.DataFrame, b1: pd.DataFrame) -> None:
    prog = b1.set_index("target_date")["b1_total_mwh"]
    err = (100 * (prog / target["target_mwh"] - 1)).dropna()
    err.index = pd.DatetimeIndex(err.index)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.scatter(err.index, err, s=3, c=LIGHT, linewidths=0, label="Daily")
    ax.plot(err.index, err.rolling(30).mean(), color=BLUE, lw=1.2, label="30-day mean")
    ax.axhline(0, color=TEXT_2, lw=0.8)
    ax.set_ylim(-15, 15)
    ax.set_title("Operator day-ahead programme vs actual, % (same definition)")
    ax.set_ylabel("programme / actual - 1, %")
    ax.legend(loc="upper left", ncols=2)
    ax.text(
        0.0,
        -0.14,
        "Programme = net demand + losses + pumping. A few days beyond "
        "±15 % are clipped (e.g. 2019-06-16 blackout).",
        transform=ax.transAxes,
        color=TEXT_2,
        fontsize=8,
    )
    save(fig, "programme_error.png")


def daily_report_error(prov: pd.DataFrame) -> None:
    p = prov.dropna(subset=["supply_dev"]).copy()
    p["pct"] = 100 * p["supply_dev"]
    caught = ((p["r1"] - 1).abs() > K1) | (p["supply_mwh"] <= 0)
    x = pd.to_datetime(p["date"])
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.scatter(
        x[~caught],
        p.loc[~caught, "pct"].clip(-30, 30),
        s=4,
        c=BLUE,
        linewidths=0,
        label="Daily report",
    )
    ax.scatter(
        x[caught],
        p.loc[caught, "pct"].clip(-30, 30),
        s=18,
        c=RED,
        marker="x",
        label="Rejected by the proposed check",
    )
    ax.axhspan(-2, 2, color=GRID, alpha=0.6, lw=0)
    ax.set_ylim(-31, 31)
    ax.set_title("Daily report vs corrected report one month later, % of supply")
    ax.set_ylabel("daily / complement - 1, %")
    ax.legend(loc="upper left", ncols=2)
    ax.text(
        0.0,
        -0.14,
        "Grey band: ±2 %. Values beyond ±30 % drawn at the edge "
        "(the four -100 % points are empty backup files, June 2020).",
        transform=ax.transAxes,
        color=TEXT_2,
        fontsize=8,
    )
    save(fig, "daily_report_error.png")


def main() -> int:
    style()
    target, prov, b1 = load()
    target_daily(target)
    target_vs_temperature(target)
    programme_error(target, b1)
    daily_report_error(prov)
    print("figures written to", FIG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
