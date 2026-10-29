"""Train the production model on the labels published by a date and save it.

Model: F-tree, 5-year window, GFS weather (src/sadi_forecast/production.py). Training
labels end at targets.definitive_available_until(as_of). Output:
models/<as_of>/model.joblib and meta.json (not committed).

Usage (after build_tables.py and build_features.py):
    uv run python scripts/train_model.py                 # as of today (Argentina)
    uv run python scripts/train_model.py --as-of 2026-10-01
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from sadi_forecast.production import save, train

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data" / "interim" / "features_daily.parquet"
MODELS = ROOT / "models"


def today_art() -> dt.date:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)).date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", type=dt.date.fromisoformat, default=today_art())
    args = p.parse_args(argv)
    features = pd.read_parquet(FEATURES)
    model, meta = train(features, args.as_of)
    path = save(model, meta, MODELS)
    print(json.dumps(asdict(meta), indent=2))
    print(f"saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
