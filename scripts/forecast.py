"""Forecast the supplied energy of one day with the production model.

Inputs as known at the issue time (10:00 ART on the day before): Post Operativo
versions published before it, the operator programme of the lag days (exports and
validity check only), GFS temperature forecast 48 h before each valid hour, calendar.
The model is the newest one trained on or before the issue date.

Weather:
    live    files from get_weather.py --live fetched on the issue date (production)
    replay  archived GFS previous runs (data/raw/open_meteo/gfs_prev), for past days

Output: data/forecasts/<day>.json (live; the first forecast of a day is kept, later
runs go to <day>_rerun_<time>.json) or data/forecasts/replay/<day>.json.

Usage (after the collector, build_tables.py --only d6 d8, get_weather.py --live and
train_model.py):
    uv run python scripts/forecast.py                    # tomorrow, live weather
    uv run python scripts/forecast.py --day 2025-06-10 --weather replay
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from sadi_forecast.daily import b1_daily
from sadi_forecast.features import issue_time, weather_daily
from sadi_forecast.live_features import GFS_COLUMN, features_for
from sadi_forecast.production import forecast_day, latest_version, load
from sadi_forecast.weather import build_weather, load_response

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RAW_WEATHER = ROOT / "data" / "raw" / "open_meteo"
OUT = ROOT / "data" / "forecasts"
MODELS = ROOT / "models"
WEIGHTS = ROOT / "results" / "point_weights.csv"


def now_art() -> dt.datetime:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)).replace(tzinfo=None)


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def live_weather(issue_date: dt.date) -> pd.DataFrame:
    files = sorted((RAW_WEATHER / "gfs_live").glob(f"*/{issue_date.isoformat()}.json"))
    if not files:
        raise FileNotFoundError(f"no live weather for {issue_date}: get_weather --live")
    return pd.concat([load_response(f) for f in files], ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--day", type=dt.date.fromisoformat)
    p.add_argument("--weather", choices=["live", "replay"], default="live")
    args = p.parse_args(argv)
    run_at = now_art()
    day = args.day or run_at.date() + dt.timedelta(days=1)
    issue = issue_time(day)
    issue_date = issue.date()

    postop = _dates(pd.read_parquet(INTERIM / "d8_postop_versions.parquet"))
    supply = _dates(pd.read_parquet(INTERIM / "d7_supply_hourly.parquet"))
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))
    weights = pd.read_csv(WEIGHTS, index_col="point")["weight"]
    if args.weather == "live":
        hourly = live_weather(issue_date)
    else:
        hourly = build_weather(RAW_WEATHER, "gfs_prev")
    gfs = weather_daily(hourly, GFS_COLUMN)

    features = features_for(day, postop, supply, b1, gfs, weights)
    model, meta = load(latest_version(MODELS, issue_date))
    rec = forecast_day(model, meta, features, day)
    rec.update(
        {
            "issue_time_art": issue.isoformat(),
            "run_at_art": run_at.isoformat(timespec="seconds"),
            "late": run_at > issue,
            "weather": args.weather,
        }
    )
    if args.weather == "live":
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{day.isoformat()}.json"
        if path.exists():
            path = OUT / f"{day.isoformat()}_rerun_{run_at:%Y%m%dT%H%M%S}.json"
    else:
        (OUT / "replay").mkdir(parents=True, exist_ok=True)
        path = OUT / "replay" / f"{day.isoformat()}.json"
    path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rec, indent=2))
    if rec["late"]:
        print("WARNING: run after the issue time; inputs are still those of the issue")
    print(f"written {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
