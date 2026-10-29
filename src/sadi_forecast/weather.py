"""Open-Meteo raw responses (scripts/get_weather.py) to one hourly table per source."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ART_OFFSET = pd.Timedelta(hours=-3)  # Argentina, no DST


def load_response(path: Path) -> pd.DataFrame:
    """One response file: time_utc, time_art, point, grid info, one column per variable.

    Variable suffixes _previous_day1/_previous_day2 are kept as they are.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    hourly = dict(data["hourly"])
    times = pd.to_datetime(hourly.pop("time"), utc=True)
    df = pd.DataFrame(hourly)
    df.insert(0, "time_utc", times)
    df.insert(1, "time_art", (times + ART_OFFSET).tz_localize(None))
    req = data.get("_request", {})
    df["point"] = req.get("point", {}).get("key", path.parent.name)
    df["grid_lat"] = data.get("latitude")
    df["grid_lon"] = data.get("longitude")
    df["grid_elevation_m"] = data.get("elevation")
    return df


def build_weather(raw_dir: Path, source: str) -> pd.DataFrame:
    """All points and years of one source; a closed year wins over a partial file."""
    frames = [
        load_response(path) for path in sorted((raw_dir / source).glob("*/*.json"))
    ]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["point", "time_utc"], keep="first")
    return out.sort_values(["point", "time_utc"]).reset_index(drop=True)
