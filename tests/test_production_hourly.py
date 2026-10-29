import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sadi_forecast.hourly import FEATURES, HOURS
from sadi_forecast.live_features import GFS_COLUMN
from sadi_forecast.production_hourly import (
    ShapeMeta,
    forecast_hourly,
    merge_hourly_weather,
)
from sadi_forecast.service import _curve_errors, site_data
from sadi_forecast.store import LocalStore


def _weather(values: list[float | None], hour0: int = 0) -> pd.DataFrame:
    t = pd.date_range("2026-10-01", periods=len(values), freq="h", tz="UTC")
    t = t + pd.Timedelta(hours=hour0)
    return pd.DataFrame(
        {
            "point": "caba",
            "time_utc": t,
            "time_art": (t - pd.Timedelta(hours=3)).tz_localize(None),
            GFS_COLUMN: values,
        }
    )


def test_merge_hourly_weather_newest_wins_without_gaps() -> None:
    old = _weather([10.0, 11.0, 12.0])
    new = _weather([20.0, None], hour0=1)
    out = merge_hourly_weather(new, old)
    assert out[GFS_COLUMN].tolist() == [10.0, 20.0, 12.0]


def test_curve_errors() -> None:
    actual = [100.0] * 24
    actual[19] = 200.0
    pred = [110.0] * 24
    pred[20] = 220.0
    e = _curve_errors(pred, actual)
    assert e["peak_error_pct"] == 10.0 and e["peak_hour_error_h"] == 1
    assert e["hourly_mape_pct"] == round((22 * 10 + 45 + 120) / 24, 3)
    assert _curve_errors(pred, None)["hourly_mape_pct"] is None


class _Zero:
    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(x))


def test_forecast_hourly_adds_up_to_daily() -> None:
    s0 = np.arange(1, 25, dtype=float)
    x = pd.DataFrame({"date": dt.date(2026, 10, 2), "hour": HOURS, "s0": s0 / s0.sum()})
    for c in FEATURES:
        if c not in x:
            x[c] = 0.0
    meta = ShapeMeta("2026-10-01", "S1", 5, "", "", 0, 0, list(FEATURES), {}, "")
    rec = forecast_hourly(_Zero(), meta, x, 300000.0)
    hourly = rec["hourly_mwh"]
    assert isinstance(hourly, list)
    assert abs(sum(hourly) - 300000.0) < 1.0
    assert rec["peak_hour"] == 24 and rec["peak_mw"] == hourly[-1]


def test_site_data_curve_is_newest_forecast_with_hours(tmp_path: Path) -> None:
    s = LocalStore(tmp_path)
    curve = [float(h) for h in HOURS]
    for d, hourly in (("2026-10-01", curve), ("2026-10-02", None)):
        rec = {"target_date": d, "forecast_mwh": 300.0, "reference_mwh": 290.0}
        if hourly:
            rec["hourly_mwh"] = hourly
        s.write(f"forecasts/{d}.json", json.dumps(rec).encode())
    s.write(
        "scores/2026-10-01.json",
        json.dumps(
            {
                "target_date": "2026-10-01",
                "forecast_hourly_mape_pct_provisional": 3.0,
                "b1_hourly_mape_pct_provisional": 9.0,
                "b1_aligned_hourly_mape_pct_provisional": 2.0,
            }
        ).encode(),
    )
    data = site_data(s, dt.datetime(2026, 10, 2, 10))
    assert data["curve"]["date"] == "2026-10-01" and data["curve"]["peak_hour"] == 24
    assert data["curve"]["b1_mwh"] is None
    assert data["summary"]["hourly"] == {
        "days": 1,
        "mape_model_pct": 3.0,
        "mape_b1_pct": 2.0,
    }


# --- isolation of the hourly part from the daily forecast (audit 2026-10-29, v2) -----


def _boom(*args: object, **kwargs: object) -> None:
    raise RuntimeError("boom")


def test_forecast_is_stored_when_the_curve_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sadi_forecast.service as sv

    s = LocalStore(tmp_path)
    day = dt.date(2026, 10, 31)
    monkeypatch.setattr(
        sv,
        "_tables",
        lambda store: dict.fromkeys(("postop", "supply", "b1", "gfs", "d6")),
    )
    monkeypatch.setattr(sv, "features_for", lambda *a: None)
    monkeypatch.setattr(sv, "_load_champion", lambda store, tmp: (None, None))
    monkeypatch.setattr(
        sv,
        "forecast_day",
        lambda *a: {"target_date": day.isoformat(), "forecast_mwh": 300000.0},
    )
    monkeypatch.setattr(sv, "issue_fetch_missing_hours", lambda *a: 0)
    monkeypatch.setattr(sv, "_load_champion_shape", lambda store, tmp: (None, None))
    monkeypatch.setattr(sv, "_gfs_hourly", lambda store: None)
    monkeypatch.setattr(sv, "design_for_day", _boom)
    rec = sv.forecast(s, day, dt.datetime(2026, 10, 30, 9, 55))
    stored = json.loads(s.read(f"forecasts/{day.isoformat()}.json"))
    assert stored["forecast_mwh"] == 300000.0
    assert stored["hourly_error"] == "RuntimeError: boom" == rec["hourly_error"]
    assert "hourly_mwh" not in stored


def test_curve_needs_a_complete_issue_time_fetch(tmp_path: Path) -> None:
    import sadi_forecast.service as sv
    from sadi_forecast.points import POINTS

    s = LocalStore(tmp_path)
    day = dt.date(2026, 10, 31)
    weights = pd.Series({POINTS[0].key: 1.0})
    assert sv.issue_fetch_missing_hours(s, day, weights) is None
    # 2026-10-30 00:00 UTC .. 2026-11-01 23:00 UTC; the target day in ART is
    # 2026-10-31 03:00 UTC .. 2026-11-01 02:00 UTC.
    t = pd.date_range("2026-10-30", periods=72, freq="h")
    values: list[float | None] = [20.0] * 72
    values[30] = None  # 2026-10-31 06:00 UTC = 03:00 ART on the target day
    data = {
        "hourly": {
            "time": [x.strftime("%Y-%m-%dT%H:%M") for x in t],
            GFS_COLUMN: values,
        }
    }
    s.write(
        f"raw/open_meteo/gfs_live/{POINTS[0].key}/2026-10-30.json",
        json.dumps(data).encode(),
    )
    assert sv.issue_fetch_missing_hours(s, day, weights) == 1
    rec = sv._hourly_record(s, {}, pd.DataFrame(), day, 1.0, 1)
    assert "missing in the issue-time weather fetch" in str(rec["hourly_error"])


def test_weather_update_survives_an_hourly_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sadi_forecast.service as sv
    from sadi_forecast.store import write_parquet

    s = LocalStore(tmp_path)
    write_parquet(s, sv.STATE["gfs"], pd.DataFrame())
    t = pd.date_range("2026-10-29", periods=48, freq="h")
    body = json.dumps(
        {
            "hourly": {
                "time": [x.strftime("%Y-%m-%dT%H:%M") for x in t],
                GFS_COLUMN: [20.0] * 48,
            }
        }
    ).encode()
    monkeypatch.setattr(sv, "merge_hourly_weather", _boom)
    sv.update_weather(s, dt.date(2026, 10, 29), lambda url: body)
    assert s.exists(sv.STATE["gfs"]) and not s.exists(sv.STATE["gfs_hourly"])


def test_daily_scores_survive_an_hourly_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sadi_forecast.service as sv

    s = LocalStore(tmp_path)
    day = dt.date(2026, 10, 20)
    s.write(
        "forecasts/2026-10-20.json",
        json.dumps(
            {
                "target_date": "2026-10-20",
                "forecast_mwh": 101.0,
                "reference_mwh": 100.0,
                "hourly_mwh": [1.0] * 24,
            }
        ).encode(),
    )
    b1 = pd.DataFrame({"target_date": [day], "b1_total_mwh": [103.0]})
    monkeypatch.setattr(
        sv, "_tables", lambda store: {"postop": 0, "supply": 0, "b1": b1, "d6": 0}
    )
    monkeypatch.setattr(sv, "valid_versions", lambda *a: None)
    monkeypatch.setattr(
        sv,
        "provisional_actuals",
        lambda v: pd.DataFrame({"value_mwh": [100.0], "kind": ["daily"]}, index=[day]),
    )
    monkeypatch.setattr(
        sv,
        "definitive_daily",
        lambda *a: pd.DataFrame({"date": [], "target_mwh": []}),
    )
    monkeypatch.setattr(sv, "_hourly_actuals", _boom)
    assert sv.score(s) == 1
    sc = json.loads(s.read("scores/2026-10-20.json"))
    assert sc["forecast_error_pct_provisional"] == 1.0
    assert "forecast_hourly_mape_pct_provisional" not in sc
