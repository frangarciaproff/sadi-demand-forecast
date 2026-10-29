"""Download hourly weather from Open-Meteo for the candidate points (D4a, D4b).

Sources:
    era5     Historical Weather API, model era5 (reanalysis), 2015-01-01 -> today-7 d
    gfs_prev Previous Runs API, model gfs_global, forecasts issued 1 and 2 days before
             (variables *_previous_day1/2), 2021-03-24 -> yesterday

Live mode (--live): for the forecast issued today, one request per point to the
Previous Runs API for the last 32 days and the next 2, variable
temperature_2m_previous_day2 only (the value forecast 48 h before each valid hour, the
same input the model was trained and tested on; DECISIONS 2026-10-29). Saved to
data/raw/open_meteo/gfs_live/<point>/<issue date>.json.

One request per (source, point, calendar year); timestamps in UTC. Raw responses go to
data/raw/open_meteo/<source>/<point>/<year>.json. Closed years are downloaded once;
the current year is stored as <year>_partial.json and refreshed on every run.
Resumable: rerun after an interruption or a daily rate-limit stop.

Open-Meteo free tier: <= 10,000 calls/day, 5,000/hour, 600/min. A request counts as
several calls (about days/14 per location with <= 10 variables), so requests are spaced.
Data: Open-Meteo.com, CC BY 4.0.

Usage (from the repository root):
    uv run python scripts/get_weather.py [--sources era5 gfs_prev] [--points caba ...]
    uv run python scripts/get_weather.py --live
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from sadi_forecast.points import POINTS, Point

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw" / "open_meteo"
USER_AGENT = "sadi-demand-forecast/0.1 (research)"
TIMEOUT_S = 120
PAUSE_S = 20.0  # keeps the estimated hourly weight below the 5,000 calls/h limit
MINUTE_WAIT_S = 65
HOUR_WAIT_S = 3700

BASE_VARS = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
)

SOURCES: dict[str, dict[str, object]] = {
    "era5": {
        "url": "https://archive-api.open-meteo.com/v1/archive",
        "model": "era5",
        "start": dt.date(2015, 1, 1),
        "lag_days": 7,
        "hourly": BASE_VARS,
    },
    "gfs_prev": {
        "url": "https://previous-runs-api.open-meteo.com/v1/forecast",
        "model": "gfs_global",
        "start": dt.date(2021, 3, 24),
        "lag_days": 1,
        "hourly": (
            *(f"{v}_previous_day2" for v in BASE_VARS),
            "temperature_2m_previous_day1",
        ),
    },
}


LIVE_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
LIVE_VARS = ("temperature_2m_previous_day2",)
LIVE_PAST_DAYS = 32
LIVE_FORECAST_DAYS = 3  # today (UTC), the target day and the next (ART is UTC-3)


class DailyLimitError(RuntimeError):
    pass


def build_url(source: str, point: Point, start: dt.date, end: dt.date) -> str:
    cfg = SOURCES[source]
    hourly = cfg["hourly"]
    assert isinstance(hourly, tuple)
    params = {
        "latitude": f"{point.lat:.4f}",
        "longitude": f"{point.lon:.4f}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(hourly),
        "models": cfg["model"],
        "timezone": "GMT",
    }
    return f"{cfg['url']}?{urllib.parse.urlencode(params)}"


def live_url(point: Point) -> str:
    params = {
        "latitude": f"{point.lat:.4f}",
        "longitude": f"{point.lon:.4f}",
        "hourly": ",".join(LIVE_VARS),
        "models": "gfs_global",
        "past_days": str(LIVE_PAST_DAYS),
        "forecast_days": str(LIVE_FORECAST_DAYS),
        "timezone": "GMT",
    }
    return f"{LIVE_URL}?{urllib.parse.urlencode(params)}"


def fetch_live(points: list[Point], pause: float) -> int:
    """Live inputs for the forecast issued today (Argentina date)."""
    now = dt.datetime.now(dt.UTC)
    issue_date = (now - dt.timedelta(hours=3)).date()
    failures = []
    for pt in points:
        path = OUT_DIR / "gfs_live" / pt.key / f"{issue_date.isoformat()}.json"
        try:
            data = json.loads(fetch(live_url(pt)))
            values = data.get("hourly", {}).get(LIVE_VARS[0], [])
            missing = sum(v is None for v in values)
            data["_request"] = {
                "point": pt._asdict(),
                "source": "gfs_live",
                "issue_date": issue_date.isoformat(),
                "fetched_utc": now.isoformat(timespec="seconds"),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            print(f"{pt.key}: ok, {len(values)} hours, {missing} missing")
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(f"{pt.key}: FAILED {exc}")
            failures.append(pt.key)
        time.sleep(pause)
    print(f"RUN SUMMARY: {len(failures)} failure(s) {failures}")
    return 1 if failures else 0


def year_ranges(
    start: dt.date, end: dt.date
) -> list[tuple[int, dt.date, dt.date, bool]]:
    """(year, first day, last day, closed) for each calendar year in [start, end]."""
    out = []
    for year in range(start.year, end.year + 1):
        first = max(start, dt.date(year, 1, 1))
        last = min(end, dt.date(year, 12, 31))
        out.append((year, first, last, last == dt.date(year, 12, 31)))
    return out


def weight(start: dt.date, end: dt.date) -> float:
    return max(1.0, ((end - start).days + 1) / 14)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                body: bytes = resp.read()
                return body
        except urllib.error.HTTPError as exc:
            reason = exc.read().decode("utf-8", "replace")
            if exc.code != 429:
                raise RuntimeError(f"HTTP {exc.code}: {reason[:300]}") from None
            low = reason.lower()
            if "daily" in low:
                raise DailyLimitError(reason[:300]) from None
            wait = HOUR_WAIT_S if "hourly" in low else MINUTE_WAIT_S
            print(f"  rate limit ({reason[:80]}); waiting {wait} s")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            print(f"  attempt {attempt} failed: {exc}")
            time.sleep(10 * attempt)
    raise RuntimeError("too many failed attempts")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--sources", nargs="+", choices=list(SOURCES), default=list(SOURCES))
    p.add_argument("--points", nargs="+", choices=[pt.key for pt in POINTS])
    p.add_argument("--pause", type=float, default=PAUSE_S, help="seconds between calls")
    p.add_argument("--live", action="store_true", help="inputs for today's forecast")
    args = p.parse_args(argv)
    points = [pt for pt in POINTS if not args.points or pt.key in args.points]
    if args.live:
        return fetch_live(points, pause=min(args.pause, 2.0))
    today = dt.datetime.now(dt.UTC).date()

    jobs = []
    for source in args.sources:
        cfg = SOURCES[source]
        assert isinstance(cfg["start"], dt.date) and isinstance(cfg["lag_days"], int)
        end = today - dt.timedelta(days=cfg["lag_days"])
        for pt in points:
            for year, first, last, closed in year_ranges(cfg["start"], end):
                name = f"{year}.json" if closed else f"{year}_partial.json"
                path = OUT_DIR / source / pt.key / name
                if closed and path.exists():
                    continue
                jobs.append((source, pt, first, last, path))
    total_w = sum(weight(j[2], j[3]) for j in jobs)
    print(
        f"{len(jobs)} requests, estimated weight {total_w:.0f} calls (limit 10,000/d)"
    )

    failures: list[str] = []
    for i, (source, pt, first, last, path) in enumerate(jobs, 1):
        label = f"[{i}/{len(jobs)}] {source} {pt.key} {first}..{last}"
        try:
            body = fetch(build_url(source, pt, first, last))
            data = json.loads(body)
            n = len(data.get("hourly", {}).get("time", []))
            expected = 24 * ((last - first).days + 1)
            if n != expected:
                raise RuntimeError(f"{n} hourly rows, expected {expected}")
            data["_request"] = {
                "point": pt._asdict(),
                "source": source,
                "start": first.isoformat(),
                "end": last.isoformat(),
                "fetched_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            for old in path.parent.glob(f"{first.year}_partial.json"):
                if old != path:
                    old.unlink()
            print(
                f"{label}: ok (grid {data.get('latitude')}, {data.get('longitude')}, "
                f"{data.get('elevation')} m)"
            )
        except DailyLimitError as exc:
            print(f"{label}: daily limit reached ({exc}). Rerun tomorrow to resume.")
            failures.append(f"{label}: daily limit")
            break
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(f"{label}: FAILED {exc}")
            failures.append(f"{label}: {exc}")
        time.sleep(args.pause)

    print(f"RUN SUMMARY: {len(failures)} failure(s)")
    for line in failures:
        print("  " + line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
