"""Production hourly curve (SPEC 11): shape model S1 on top of the v1 daily forecast.

Same code path as scripts/backtest_hourly.py: hourly.version_shapes, reference_shapes,
hourly_temperature, design_hourly, shape_target, shares_from_model; 5-year window and
the label embargo of targets.py. Saved next to the v1 model of the same version.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from sadi_forecast.daily import b1_daily
from sadi_forecast.features import LAGS, valid_versions
from sadi_forecast.hourly import (
    FEATURES,
    HOURS,
    T_COLS,
    TREES,
    definitive_hourly,
    design_hourly,
    hourly_temperature,
    programme_hourly,
    reference_shapes,
    shape_target,
    shares_from_model,
    version_shapes,
)
from sadi_forecast.live_features import GFS_COLUMN
from sadi_forecast.production import WINDOW_YEARS
from sadi_forecast.targets import definitive_available_until

SHAPE_FILE = "shape.joblib"
SHAPE_META_FILE = "shape_meta.json"
HOURLY_WEATHER_COLUMNS = ["point", "time_utc", "time_art", GFS_COLUMN]


@dataclass
class ShapeMeta:
    version: str
    model: str
    window_years: int
    train_first: str
    train_last: str
    n_days: int
    n_rows: int
    features: list[str]
    tree_params: dict[str, object]
    sklearn: str


def merge_hourly_weather(new: pd.DataFrame, old: pd.DataFrame) -> pd.DataFrame:
    """The newest fetch wins on the hours it has a value for (as gfs_daily)."""
    new = new[HOURLY_WEATHER_COLUMNS].dropna(subset=[GFS_COLUMN])
    parts = [new] if old.empty else [new, old[HOURLY_WEATHER_COLUMNS]]
    out = pd.concat(parts, ignore_index=True)
    out = out.drop_duplicates(subset=["point", "time_utc"], keep="first")
    return out.sort_values(["point", "time_utc"]).reset_index(drop=True)


def _design(
    features: pd.DataFrame,
    postop: pd.DataFrame,
    programme: pd.DataFrame,
    gfs_hourly: pd.DataFrame,
    weights: pd.Series,
    days: list[dt.date],
) -> pd.DataFrame:
    b1 = b1_daily(programme)
    shapes = version_shapes(valid_versions(postop, b1), programme_hourly(programme))
    s0, used = reference_shapes(shapes, days)
    lo = min(days) - dt.timedelta(days=LAGS)
    hi = max(days)
    w = gfs_hourly[[lo <= d <= hi for d in gfs_hourly["time_art"].dt.date]]
    temp = hourly_temperature(w, GFS_COLUMN, weights)
    return design_hourly(features, s0, temp, used, days)


def train_shape(
    features: pd.DataFrame,
    postop: pd.DataFrame,
    programme: pd.DataFrame,
    supply: pd.DataFrame,
    gfs_hourly: pd.DataFrame,
    weights: pd.Series,
    as_of: dt.date,
) -> tuple[HistGradientBoostingRegressor, ShapeMeta]:
    last = definitive_available_until(as_of)
    nxt = last + dt.timedelta(days=1)
    first = nxt.replace(year=nxt.year - WINDOW_YEARS)
    days = [d for d in features.index if first <= d <= last]
    x = _design(features, postop, programme, gfs_hourly, weights, days)
    y = shape_target(x, definitive_hourly(supply))
    keep = y.notna().to_numpy()
    x, y = x[keep], y[keep]
    n_days = x["date"].nunique()
    if n_days < 365:
        raise ValueError(f"only {n_days} shape training days on {as_of}")
    model = HistGradientBoostingRegressor(**TREES).fit(x[FEATURES], y)
    meta = ShapeMeta(
        version=as_of.isoformat(),
        model="S1",
        window_years=WINDOW_YEARS,
        train_first=min(x["date"]).isoformat(),
        train_last=max(x["date"]).isoformat(),
        n_days=int(n_days),
        n_rows=len(x),
        features=list(FEATURES),
        tree_params=dict(TREES),
        sklearn=sklearn.__version__,
    )
    assert first <= min(x["date"]) and max(x["date"]) <= last
    return model, meta


def save_shape(
    model: HistGradientBoostingRegressor, meta: ShapeMeta, folder: Path
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, folder / SHAPE_FILE)
    (folder / SHAPE_META_FILE).write_text(
        json.dumps(asdict(meta), indent=2) + "\n", encoding="utf-8"
    )


def load_shape(folder: Path) -> tuple[HistGradientBoostingRegressor, ShapeMeta]:
    meta = ShapeMeta(**json.loads((folder / SHAPE_META_FILE).read_text("utf-8")))
    model: HistGradientBoostingRegressor = joblib.load(folder / SHAPE_FILE)
    return model, meta


def design_for_day(
    features: pd.DataFrame,
    postop: pd.DataFrame,
    programme: pd.DataFrame,
    gfs_hourly: pd.DataFrame,
    weights: pd.Series,
    day: dt.date,
) -> pd.DataFrame:
    """The 24 S1 input rows of `day` (features must hold the row of `day`)."""
    x = _design(features, postop, programme, gfs_hourly, weights, [day])
    if len(x) != 24:
        raise ValueError(
            f"cannot forecast the hourly curve of {day}: "
            "fewer than two reference shapes or incomplete hourly weather"
        )
    return x


def forecast_hourly(
    model: HistGradientBoostingRegressor,
    meta: ShapeMeta,
    x: pd.DataFrame,
    daily_mwh: float,
) -> dict[str, object]:
    """Hourly forecast (hour h covers h-1..h ART) and daily peak from the 24 rows."""
    if list(FEATURES) != meta.features:
        raise ValueError("shape feature columns differ from the trained model")
    shares = shares_from_model(x, model.predict(x[FEATURES])).iloc[0]
    hourly = [round(float(daily_mwh * shares[h]), 1) for h in HOURS]
    peak = max(hourly)
    return {
        "hourly_mwh": hourly,
        "peak_mw": peak,
        "peak_hour": HOURS[hourly.index(peak)],
        "shape_model": meta.model,
        "shape_model_version": meta.version,
    }


def programme_curve(prog: pd.DataFrame, day: dt.date) -> list[float] | None:
    """The operator's hourly programme (t01..t24) for `day` from a programme_hourly
    table, if published."""
    if day not in prog.index or prog.loc[day, T_COLS].isna().any():
        return None
    return [round(float(v), 1) for v in prog.loc[day, T_COLS].to_numpy(dtype=float)]
