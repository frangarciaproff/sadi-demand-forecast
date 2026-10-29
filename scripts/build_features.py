"""Build the daily feature table (data/interim/features_daily.parquet).

Also writes the point weights (O3) computed on the training period to
results/point_weights.csv.

Requires build_tables.py --only d5 d6 d7 d8 and the Open-Meteo download.

Usage (from the repository root):
    uv run python scripts/build_features.py
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path

import pandas as pd

from sadi_forecast.daily import b1_daily
from sadi_forecast.features import build_features, valid_versions, weather_daily
from sadi_forecast.targets import definitive_daily
from sadi_forecast.weather import build_weather
from sadi_forecast.weights import point_weights

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
RAW_WEATHER = ROOT / "data" / "raw" / "open_meteo"
TRAIN_WEIGHTS = (dt.date(2019, 1, 1), dt.date(2024, 9, 30))  # province sheet from 2019
FIRST_DAY = dt.date(2018, 1, 1)
LAST_DAY = dt.date(2026, 9, 30)
WEATHER_COLUMNS = {
    "era5": "temperature_2m",
    "gfs": "temperature_2m_previous_day2",
}
WEATHER_SOURCES = {"era5": "era5", "gfs": "gfs_prev"}


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    postop = _dates(pd.read_parquet(INTERIM / "d8_postop_versions.parquet"))
    supply = _dates(pd.read_parquet(INTERIM / "d7_supply_hourly.parquet"))
    provinces = _dates(pd.read_parquet(INTERIM / "d7_sintesis_province_hourly.parquet"))
    d5 = _dates(pd.read_parquet(INTERIM / "d5_area_hourly.parquet"))
    b1 = b1_daily(pd.read_parquet(INTERIM / "d6_programme_hourly.parquet"))

    weights = point_weights(provinces, d5, *TRAIN_WEIGHTS)
    out = ROOT / "results"
    out.mkdir(parents=True, exist_ok=True)
    weights.round(5).to_csv(out / "point_weights.csv", index_label="point")
    logging.info("weights:\n%s", weights.round(4).to_string())

    weather = {}
    for name, folder in WEATHER_SOURCES.items():
        hourly = build_weather(RAW_WEATHER, folder)
        if hourly.empty:
            logging.warning("no %s files; weather columns for it are skipped", folder)
            continue
        weather[name] = weather_daily(hourly, WEATHER_COLUMNS[name])

    days = [
        FIRST_DAY + dt.timedelta(days=k) for k in range((LAST_DAY - FIRST_DAY).days + 1)
    ]
    table = build_features(
        definitive_daily(postop, supply),
        valid_versions(postop, b1),
        b1,
        weather,
        weights["weight"],
        days,
    )
    table.to_parquet(INTERIM / "features_daily.parquet")
    logging.info(
        "features_daily: %d days, %d columns; missing share per column (top):\n%s",
        len(table),
        table.shape[1],
        table.isna().mean().sort_values(ascending=False).head(12).round(3).to_string(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
