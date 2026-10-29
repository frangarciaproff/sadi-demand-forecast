import datetime as dt
import json
from pathlib import Path

from sadi_forecast.service import site_data
from sadi_forecast.store import LocalStore


def _w(store: LocalStore, key: str, obj: object) -> None:
    store.write(key, json.dumps(obj).encode())


def test_site_data_compares_on_common_days(tmp_path: Path) -> None:
    s = LocalStore(tmp_path)
    for d in ("2026-10-01", "2026-10-02", "2026-10-03"):
        _w(
            s,
            f"forecasts/{d}.json",
            {
                "target_date": d,
                "forecast_mwh": 100.0,
                "reference_mwh": 90.0,
                "run_at_art": d,
                "late": False,
            },
        )
    _w(s, "forecasts/2026-10-01_rerun_x.json", {"target_date": "2026-10-01"})
    _w(
        s,
        "scores/2026-10-01.json",
        {
            "target_date": "2026-10-01",
            "forecast_error_pct_definitive": 2.0,
            "b1_error_pct_definitive": -4.0,
        },
    )
    _w(
        s,
        "scores/2026-10-02.json",
        {
            "target_date": "2026-10-02",
            "forecast_error_pct_provisional": -6.0,
            "b1_error_pct_provisional": None,
        },
    )
    data = site_data(s, dt.datetime(2026, 10, 3, 9, 30))
    assert [r["date"] for r in data["days"]] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
    ]
    best = data["summary"]["best"]
    assert best["days"] == 1 and best["definitive_days"] == 1
    assert best["mape_model_pct"] == 2.0 and best["mape_b1_pct"] == 4.0
