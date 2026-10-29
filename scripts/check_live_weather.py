"""Live weather vs archived weather for the same forecast (audit 2026-10-29, point 3).

The model was trained and tested on the archived GFS previous_day2 temperature (the
value forecast 48 h before each valid hour). In production the same variable is fetched
at the issue time. This compares, hour by hour, the live fetch saved for an issue date
with the archive fetched now, for the target day (issue date + 1, Argentina time).
Differences mean production inputs differ from training inputs (or that the archive
holds runs that did not exist at the issue time). Run it two or more days after the
target day.

Writes results/checks/live_weather_<target>.json.

Usage (network needed; from the PC):
    uv run python scripts/check_live_weather.py --issue 2026-10-29
    uv run --with boto3 python scripts/check_live_weather.py --issue 2026-10-30 \
        --bucket <bucket>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
from pathlib import Path

import pandas as pd

from sadi_forecast.openmeteo import LIVE_VARS, http_get
from sadi_forecast.points import POINTS
from sadi_forecast.store import LocalStore, S3Store, Store
from sadi_forecast.weather import response_frame

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"


def archive_url(lat: float, lon: float, day: dt.date) -> str:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "hourly": LIVE_VARS[0],
        "models": "gfs_global",
        "start_date": day.isoformat(),
        "end_date": (day + dt.timedelta(days=1)).isoformat(),
        "timezone": "GMT",
    }
    return f"{ARCHIVE_URL}?{urllib.parse.urlencode(params)}"


def day_values(frame: pd.DataFrame, target: dt.date) -> pd.Series:
    """The 24 values of the Argentina day `target`, indexed by ART time."""
    f = frame[frame["time_art"].dt.date == target]
    return f.set_index("time_art")[LIVE_VARS[0]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--issue", type=dt.date.fromisoformat, required=True)
    p.add_argument("--bucket")
    args = p.parse_args(argv)
    store: Store = S3Store(args.bucket) if args.bucket else LocalStore(ROOT / "data")
    target = args.issue + dt.timedelta(days=1)
    weights = pd.read_csv(ROOT / "results" / "point_weights.csv", index_col="point")[
        "weight"
    ]
    rows = []
    for pt in POINTS:
        key = f"raw/open_meteo/gfs_live/{pt.key}/{args.issue.isoformat()}.json"
        if not store.exists(key):
            print(f"{pt.key}: no live fetch for {args.issue}")
            continue
        live = day_values(response_frame(json.loads(store.read(key)), pt.key), target)
        arch_data = json.loads(http_get(archive_url(pt.lat, pt.lon, target)))
        arch = day_values(response_frame(arch_data, pt.key), target)
        both = pd.concat({"live": live, "archive": arch}, axis=1)
        diff = both["live"] - both["archive"]
        rows.append(
            {
                "point": pt.key,
                "weight": float(weights.get(pt.key, 0.0)),
                "hours": int(both.dropna().shape[0]),
                "hours_different": int((diff.abs() > 0.05).sum()),
                "max_abs_diff_c": round(float(diff.abs().max()), 2),
                "daily_mean_diff_c": round(float(diff.mean()), 3),
                "hours_art_different": [
                    t.strftime("%H:%M") for t in diff.index[diff.abs() > 0.05]
                ],
            }
        )
        print(rows[-1])
    table = pd.DataFrame(rows)
    w = table.set_index("point")["weight"]
    weighted = float(
        (table.set_index("point")["daily_mean_diff_c"] * w).sum() / w.sum()
    )
    out = {
        "issue_date": args.issue,
        "target_date": target,
        "checked_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "weighted_daily_mean_diff_c": round(weighted, 3),
        "points_with_any_difference": int((table["hours_different"] > 0).sum()),
        "points": rows,
    }
    folder = ROOT / "results" / "checks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"live_weather_{target.isoformat()}.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "points"}, default=str))
    print(f"written {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
