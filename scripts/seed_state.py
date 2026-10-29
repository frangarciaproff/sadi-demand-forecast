"""Seed the service state (SPEC 7) from the PC tables: data/state/ and data/models/.

state/: d6_programme_hourly, d8_postop_versions, d7_supply_hourly, features_daily
(copies of data/interim) and gfs_daily (daily mean GFS previous_day2 temperature per
point, from the archived previous runs and the live files). models/<version>/ and
models/champion.json from models/. Then upload with the AWS CLI (cheatsheet).

Usage (after build_tables.py, build_features.py and train_model.py):
    uv run python scripts/seed_state.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

from sadi_forecast.features import weather_daily
from sadi_forecast.live_features import GFS_COLUMN
from sadi_forecast.service import CHAMPION, STATE
from sadi_forecast.store import LocalStore, write_parquet
from sadi_forecast.weather import build_weather

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INTERIM = DATA / "interim"
RAW_WEATHER = DATA / "raw" / "open_meteo"
MODELS = ROOT / "models"


def main() -> int:
    store = LocalStore(DATA)
    for name, file in (
        ("d6", "d6_programme_hourly.parquet"),
        ("d8", "d8_postop_versions.parquet"),
        ("d7", "d7_supply_hourly.parquet"),
        ("features", "features_daily.parquet"),
    ):
        write_parquet(store, STATE[name], pd.read_parquet(INTERIM / file))
        print(f"{STATE[name]} <- {file}")
    hourly = pd.concat(
        [
            build_weather(RAW_WEATHER, "gfs_prev"),
            build_weather(RAW_WEATHER, "gfs_live"),
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["point", "time_utc"], keep="first")
    gfs = weather_daily(hourly, GFS_COLUMN)
    write_parquet(store, STATE["gfs"], gfs)
    print(f"{STATE['gfs']}: {len(gfs)} days, {gfs.index.min()} -> {gfs.index.max()}")
    version = max(p.name for p in MODELS.iterdir() if (p / "model.joblib").exists())
    target = DATA / "models" / version
    target.mkdir(parents=True, exist_ok=True)
    for name in ("model.joblib", "meta.json"):
        shutil.copy2(MODELS / version / name, target / name)
    store.write(CHAMPION, (json.dumps({"version": version}) + "\n").encode())
    print(f"champion: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
