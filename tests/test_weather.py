"""Weather download helpers and table builder (no network)."""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from pathlib import Path

import pandas as pd

from get_weather import build_url, year_ranges
from sadi_forecast.points import POINTS
from sadi_forecast.weather import build_weather


def test_year_ranges_marks_open_year() -> None:
    r = year_ranges(dt.date(2021, 3, 24), dt.date(2022, 5, 1))
    assert r == [
        (2021, dt.date(2021, 3, 24), dt.date(2021, 12, 31), True),
        (2022, dt.date(2022, 1, 1), dt.date(2022, 5, 1), False),
    ]


def test_build_url_gfs_previous_runs() -> None:
    url = build_url("gfs_prev", POINTS[0], dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["models"] == ["gfs_global"]
    assert q["timezone"] == ["GMT"]
    assert "temperature_2m_previous_day2" in q["hourly"][0].split(",")


def _response(path: Path, value: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "latitude": -34.6,
        "longitude": -58.4,
        "elevation": 25.0,
        "hourly": {
            "time": ["2024-12-31T02:00", "2024-12-31T03:00"],
            "temperature_2m": [value, value],
        },
        "_request": {"point": {"key": "caba"}},
    }
    path.write_text(json.dumps(data))


def test_build_weather_closed_year_wins_and_art_time(tmp_path: Path) -> None:
    _response(tmp_path / "era5" / "caba" / "2024.json", 20.0)
    _response(tmp_path / "era5" / "caba" / "2024_partial.json", 99.0)
    wx = build_weather(tmp_path, "era5")
    assert len(wx) == 2
    assert (wx["temperature_2m"] == 20.0).all()
    assert wx["time_art"].iloc[1] == pd.Timestamp("2024-12-31 00:00")
