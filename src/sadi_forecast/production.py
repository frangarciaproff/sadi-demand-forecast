"""Production model: training, storage and one-day forecasts.

Configuration (DECISIONS 2026-10-29, after the re-audit):
F-hyb, 5-year window, M-fc (GFS previous_day2 for the target day and the reference
days, in training and in forecasting). The same code path as the backtest is used:
models.design, models.relative_target, the label embargo of targets.py.
"""

from __future__ import annotations

import datetime as dt
import json
import platform
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from sadi_forecast.models import FAMILIES, TREE_PARAMS, Model, design, relative_target
from sadi_forecast.targets import definitive_available_until

FAMILY = "hyb"
WINDOW_YEARS = 5
WEATHER = "gfs"
MODEL_FILE = "model.joblib"
META_FILE = "meta.json"


@dataclass
class ModelMeta:
    version: str  # training date (as_of), ISO
    family: str
    window_years: int
    weather: str
    train_first: str
    train_last: str
    n_train: int
    features: list[str]
    tree_params: dict[str, object]
    sklearn: str
    python: str


def training_rows(
    features: pd.DataFrame, as_of: dt.date
) -> tuple[pd.DataFrame, pd.Series, dt.date, dt.date]:
    """Design matrix and relative target of the days usable on date `as_of`."""
    last = definitive_available_until(as_of)
    nxt = last + dt.timedelta(days=1)
    first = nxt.replace(year=nxt.year - WINDOW_YEARS)
    f = features[[first <= d <= last for d in features.index]]
    x = design(f, WEATHER, WEATHER)
    y = relative_target(f)
    keep = y.notna() & x["d_t"].notna()
    return x[keep], y[keep], first, last


def train(features: pd.DataFrame, as_of: dt.date) -> tuple[Model, ModelMeta]:
    x, y, first, last = training_rows(features, as_of)
    if len(x) < 365:
        raise ValueError(f"only {len(x)} training days on {as_of}")
    model = FAMILIES[FAMILY]().fit(x, y)
    meta = ModelMeta(
        version=as_of.isoformat(),
        family=FAMILY,
        window_years=WINDOW_YEARS,
        weather=WEATHER,
        train_first=min(x.index).isoformat(),
        train_last=max(x.index).isoformat(),
        n_train=len(x),
        features=list(x.columns),
        tree_params=dict(TREE_PARAMS),
        sklearn=sklearn.__version__,
        python=platform.python_version(),
    )
    assert first <= min(x.index) and max(x.index) <= last
    return model, meta


def save(model: Model, meta: ModelMeta, models_dir: Path) -> Path:
    out = models_dir / meta.version
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / MODEL_FILE)
    (out / META_FILE).write_text(
        json.dumps(asdict(meta), indent=2) + "\n", encoding="utf-8"
    )
    return out


def latest_version(models_dir: Path, on: dt.date) -> Path:
    """Newest model trained on or before `on` (a forecast never uses a later model)."""
    dirs = [
        p
        for p in models_dir.iterdir()
        if p.is_dir()
        and (p / MODEL_FILE).exists()
        and dt.date.fromisoformat(p.name) <= on
    ]
    if not dirs:
        raise FileNotFoundError(f"no model in {models_dir} trained on or before {on}")
    return max(dirs, key=lambda p: p.name)


def load(path: Path) -> tuple[Model, ModelMeta]:
    meta = ModelMeta(**json.loads((path / META_FILE).read_text(encoding="utf-8")))
    model: Model = joblib.load(path / MODEL_FILE)
    return model, meta


def forecast_day(
    model: Model, meta: ModelMeta, features: pd.DataFrame, day: dt.date
) -> dict[str, object]:
    """Forecast for `day` from its feature row (features must cover day-28 .. day)."""
    x = design(features, WEATHER, WEATHER).loc[[day]]
    if list(x.columns) != meta.features:
        raise ValueError("feature columns differ from the trained model")
    row = features.loc[day]
    if pd.isna(row["ref_mwh"]) or pd.isna(x["d_t"].iloc[0]):
        missing: str = "reference level" if pd.isna(row["ref_mwh"]) else "weather"
        raise ValueError(f"cannot forecast {day}: missing {missing}")
    yhat = float(model.predict(x)[0])
    return {
        "target_date": day.isoformat(),
        "forecast_mwh": round(float(row["ref_mwh"]) * float(np.exp(yhat)), 1),
        "reference_mwh": round(float(row["ref_mwh"]), 1),
        "reference_days_used": int(row["ref_n"]),
        "relative_change": round(yhat, 5),
        "t_gfs_c": round(float(row[f"t_{WEATHER}"]), 2),
        "delta_t_vs_reference_c": round(float(x["d_t"].iloc[0]), 2),
        "latest_lag": next(
            (k for k in range(3, 29) if pd.notna(row.get(f"lag_{k}"))), None
        ),
        "model_version": meta.version,
    }
