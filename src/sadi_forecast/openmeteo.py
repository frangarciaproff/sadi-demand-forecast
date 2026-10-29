"""Open-Meteo live inputs: GFS forecast 48 h before each valid hour (previous_day2).

The same variable the model was trained and tested on (DECISIONS 2026-10-29). One
request per point covers the last 32 days and the next 2 (UTC), so the target day of
an issue at 10:00 ART is inside it, and so are the 28 reference days.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request

from sadi_forecast.points import Point

LIVE_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
LIVE_VARS = ("temperature_2m_previous_day2",)
LIVE_PAST_DAYS = 32
LIVE_FORECAST_DAYS = 3  # today (UTC), the target day and the next (ART is UTC-3)
USER_AGENT = "sadi-demand-forecast/0.1 (research)"


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


def http_get(url: str, timeout: float = 60, attempts: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for k in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body: bytes = resp.read()
                return body
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"GET failed after {attempts} attempts: {last}")
