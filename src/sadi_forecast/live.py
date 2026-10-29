"""Daily energy from the archived demand API responses (D2 snapshots, D3 by-date)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

STEP_H = 5 / 60  # 5-minute points


def daily_energy(
    points: Sequence[Mapping[str, object]], key: str, step_h: float
) -> float:
    """Trapezoidal energy (MWh) of one day from instantaneous MW points.

    Needs both day boundaries (00:00 and 24:00) and no missing point in between;
    otherwise NaN. step_h: spacing of the points in hours.
    """
    values = [p.get(key) for p in points]
    expected = round(24 / step_h) + 1
    if len(values) != expected or any(not isinstance(v, int | float) for v in values):
        return float("nan")
    v = [float(x) for x in values]  # type: ignore[arg-type]
    return step_h * (sum(v) - (v[0] + v[-1]) / 2)


def _points(path: Path, key: str) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    pts = [p for p in data if key in p]
    return sorted(pts, key=lambda p: str(p["fecha"]))


def by_date_daily(raw_dir: Path, region: int = 1002) -> pd.Series:
    """D3 actual demand per day (MWh), latest archived response per date."""
    out: dict[dt.date, float] = {}
    for folder in sorted((raw_dir / "by_date" / str(region)).iterdir()):
        files = sorted(folder.glob("*.json"))
        if not files:
            continue
        out[dt.date.fromisoformat(folder.name)] = daily_energy(
            _points(files[-1], "dem"), "dem", STEP_H
        )
    return pd.Series(out, name="d3_mwh", dtype=float)


def forecast_daily(raw_dir: Path, region: int = 1002) -> pd.Series:
    """CAMMESA intraday forecast (D2 demPrevista, 25 hourly points) per day, MWh.

    Uses the first snapshot taken on that day.
    """
    out: dict[dt.date, float] = {}
    root = raw_dir / "snapshot" / str(region)
    if not root.exists():
        return pd.Series(out, name="d2_prevista_mwh", dtype=float)
    for folder in sorted(root.iterdir()):
        files = sorted(folder.glob("*.json"))
        if not files:
            continue
        pts = _points(files[0], "demPrevista")
        out[dt.date.fromisoformat(folder.name)] = daily_energy(pts, "demPrevista", 1.0)
    return pd.Series(out, name="d2_prevista_mwh", dtype=float)
