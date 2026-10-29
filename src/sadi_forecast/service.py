"""The production service (SPEC 7): daily forecast and scoring, monthly retraining.

Every step reads and writes through a Store, so the same code runs on the PC (a local
folder, scripts/run_service.py) and in the Lambda (the S3 bucket). The steps reuse
the functions behind the training table and the backtest: tables.build_programme,
postop.build_postop, sintesis.build_supply, features.build_features,
live_features.features_for, production.train / forecast_day.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from sadi_forecast.daily import b1_daily
from sadi_forecast.features import build_features as build_feature_table
from sadi_forecast.features import (
    issue_time,
    valid_versions,
    weather_daily,
)
from sadi_forecast.live_features import GFS_COLUMN, features_for
from sadi_forecast.openmeteo import LIVE_VARS, http_get, live_url
from sadi_forecast.points import POINTS
from sadi_forecast.postop import NEMO as POSTOP_NEMO
from sadi_forecast.postop import build_postop
from sadi_forecast.production import forecast_day, load, save, train
from sadi_forecast.sintesis import build_supply
from sadi_forecast.sintesis_web import BASES, SITE, YEAR_PAGE, find_bases
from sadi_forecast.store import Store, read_parquet, write_parquet
from sadi_forecast.tables import PROGRAMME, build_programme
from sadi_forecast.targets import definitive_daily
from sadi_forecast.weather import response_frame

log = logging.getLogger(__name__)

RAW = "raw/cammesa/"
STATE = {
    "d6": "state/d6_programme_hourly.parquet",
    "d8": "state/d8_postop_versions.parquet",
    "d7": "state/d7_supply_hourly.parquet",
    "gfs": "state/gfs_daily.parquet",
    "features": "state/features_daily.parquet",
}
CHAMPION = "models/champion.json"
DOC_WINDOW_DAYS = 45  # the collector's look-back for late re-publications
INDEX_EXTRA_DAYS = 60  # listing windows start up to 45 days before a document
FIRST_DAY = dt.date(2018, 1, 1)

Fetch = Callable[[str], bytes]


def now_art() -> dt.datetime:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)).replace(tzinfo=None)


def _dates(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    df[col] = pd.to_datetime(df[col]).dt.date
    return df


def _json(obj: object) -> bytes:
    return (json.dumps(obj, indent=2, default=str) + "\n").encode("utf-8")


# --- state tables -------------------------------------------------------------------


def _stage_new_docs(
    store: Store, nemo: str, known: set[str], today: dt.date, tmp: Path
) -> int:
    """Copy the zips listed in the last DOC_WINDOW_DAYS that are not in the table yet,
    with the newest listing file of each window, into the archive layout under tmp."""
    n = 0
    for k in range(DOC_WINDOW_DAYS + 1):
        day = today - dt.timedelta(days=DOC_WINDOW_DAYS - k)
        for key in store.list(f"{RAW}docs/{nemo}/{day.isoformat()}/"):
            name = key.rsplit("/", 1)[1]
            if not name.endswith(".zip") or name.split("_", 1)[0] in known:
                continue
            dest = tmp / "docs" / nemo / day.isoformat() / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(store.read(key))
            n += 1
    if n:
        span = DOC_WINDOW_DAYS + INDEX_EXTRA_DAYS
        for k in range(span + 1):
            w0 = (today - dt.timedelta(days=span - k)).isoformat()
            files = [
                f
                for f in store.list(f"{RAW}docs_index/{nemo}/{w0}/")
                if f.endswith(".json") and not f.endswith(".error.json")
            ]
            if files:
                dest = tmp / "docs_index" / nemo / w0 / files[-1].rsplit("/", 1)[1]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(store.read(files[-1]))
    return n


def update_state(store: Store, today: dt.date) -> dict[str, int]:
    """Add the new programme (D6) and Post Operativo (D8) documents to the tables."""
    added: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        d6 = read_parquet(store, STATE["d6"])
        n6 = _stage_new_docs(
            store, PROGRAMME, set(d6["doc_id"].astype(str)), today, tmp
        )
        if n6:
            new = build_programme(tmp)
            d6 = pd.concat([d6, new], ignore_index=True).drop_duplicates(
                subset=["doc_id", "target_date", "source"], keep="last"
            )
            write_parquet(store, STATE["d6"], d6)
        added["d6_documents"] = n6
        d8 = read_parquet(store, STATE["d8"])
        n8 = _stage_new_docs(
            store, POSTOP_NEMO, set(d8["doc_id"].astype(str)), today, tmp
        )
        if n8:
            new = build_postop(tmp, tmp / "cache", workers=2)
            d8 = pd.concat([d8, new], ignore_index=True).drop_duplicates(
                subset=["doc_id"], keep="last"
            )
            write_parquet(store, STATE["d8"], d8)
        added["d8_documents"] = n8
    return added


def update_weather(store: Store, issue_date: dt.date, fetch: Fetch) -> int:
    """Fetch the live GFS inputs, archive them and merge them into gfs_daily."""
    frames = []
    for pt in POINTS:
        data = json.loads(fetch(live_url(pt)))
        values = data.get("hourly", {}).get(LIVE_VARS[0], [])
        data["_request"] = {
            "point": pt._asdict(),
            "source": "gfs_live",
            "issue_date": issue_date.isoformat(),
        }
        store.write(
            f"raw/open_meteo/gfs_live/{pt.key}/{issue_date.isoformat()}.json",
            json.dumps(data).encode("utf-8"),
        )
        frames.append(response_frame(data, pt.key))
        log.info("%s: %d hours, %d missing", pt.key, len(values), values.count(None))
    new = weather_daily(pd.concat(frames, ignore_index=True), GFS_COLUMN)
    old = read_parquet(store, STATE["gfs"])
    # The newest fetch wins on the days it covers: an earlier fetch may hold values for
    # hours whose 48-h run did not exist yet when it ran.
    merged = new.combine_first(old)
    write_parquet(store, STATE["gfs"], merged)
    return len(merged) - len(old)


# --- daily --------------------------------------------------------------------------


def _tables(store: Store) -> dict[str, Any]:
    d6 = read_parquet(store, STATE["d6"])
    return {
        "postop": _dates(read_parquet(store, STATE["d8"])),
        "supply": _dates(read_parquet(store, STATE["d7"])),
        "b1": b1_daily(d6),
        "gfs": read_parquet(store, STATE["gfs"]),
    }


def _weights() -> pd.Series:
    from importlib.resources import files

    text = files("sadi_forecast").joinpath("data/point_weights.csv").read_text()
    return pd.read_csv(io.StringIO(text), index_col="point")["weight"]


def _load_champion(store: Store, tmp: Path) -> tuple[Any, Any]:
    version = json.loads(store.read(CHAMPION))["version"]
    folder = tmp / version
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("model.joblib", "meta.json"):
        (folder / name).write_bytes(store.read(f"models/{version}/{name}"))
    return load(folder)


def forecast(store: Store, day: dt.date, run_at: dt.datetime) -> dict[str, object]:
    """Forecast `day` once; an existing forecast is returned unchanged."""
    key = f"forecasts/{day.isoformat()}.json"
    if store.exists(key):
        existing: dict[str, object] = json.loads(store.read(key))
        return existing
    t = _tables(store)
    features = features_for(
        day, t["postop"], t["supply"], t["b1"], t["gfs"], _weights()
    )
    with tempfile.TemporaryDirectory() as tmp:
        model, meta = _load_champion(store, Path(tmp))
    rec = forecast_day(model, meta, features, day)
    issue = issue_time(day)
    rec.update(
        {
            "issue_time_art": issue.isoformat(),
            "run_at_art": run_at.isoformat(timespec="seconds"),
            "late": run_at > issue,
            "weather": "live",
        }
    )
    store.write(key, _json(rec))
    return rec


def _pct(pred: float | None, actual: float | None) -> float | None:
    if pred is None or actual is None or pd.isna(pred) or pd.isna(actual):
        return None
    return round(100 * (pred / actual - 1), 3)


def score(store: Store) -> int:
    """Score every forecast whose actuals exist (provisional, then definitive)."""
    days = [
        dt.date.fromisoformat(k.rsplit("/", 1)[1][:10])
        for k in store.list("forecasts/")
        if k.endswith(".json") and "_rerun_" not in k
    ]
    if not days:
        return 0
    t = _tables(store)
    versions = valid_versions(t["postop"], t["b1"])
    first = (
        versions[versions["kind"] == "daily"]
        .sort_values("published_art")
        .groupby("date")
        .head(1)
        .set_index("date")
    )
    defin = definitive_daily(t["postop"], t["supply"]).dropna(subset=["target_mwh"])
    target = dict(zip(defin["date"], defin["target_mwh"].astype(float), strict=True))
    b1_rows = t["b1"].dropna(subset=["b1_total_mwh"])
    b1 = dict(
        zip(b1_rows["target_date"], b1_rows["b1_total_mwh"].astype(float), strict=True)
    )
    prov_value = dict(zip(first.index, first["value_mwh"].astype(float), strict=True))
    prov_valid = dict(zip(first.index, first["valid"].astype(bool), strict=True))
    n = 0
    for day in days:
        key = f"scores/{day.isoformat()}.json"
        old = json.loads(store.read(key)) if store.exists(key) else {}
        if old.get("definitive_mwh") is not None:
            continue
        fc = json.loads(store.read(f"forecasts/{day.isoformat()}.json"))
        definitive = target.get(day)
        b1_day = b1.get(day)
        rec: dict[str, Any] = {
            "target_date": day.isoformat(),
            "forecast_mwh": fc["forecast_mwh"],
            "b0_mwh": fc["reference_mwh"],
            "b1_mwh": b1_day,
            "provisional_mwh": prov_value.get(day),
            "provisional_valid": prov_valid.get(day),
            "definitive_mwh": definitive,
        }
        if rec["provisional_mwh"] is None and rec["definitive_mwh"] is None:
            continue
        for actual in ("provisional", "definitive"):
            a = rec[f"{actual}_mwh"]
            for name in ("forecast", "b0", "b1"):
                rec[f"{name}_error_pct_{actual}"] = _pct(rec[f"{name}_mwh"], a)
        if rec != old:
            store.write(key, _json(rec))
            n += 1
    return n


SITE_DATA = "data.json"
SITE_DAYS = 90


def _mape(errors: list[float | None]) -> float | None:
    vals = [abs(e) for e in errors if e is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def site_data(store: Store, now: dt.datetime) -> dict[str, Any]:
    """The public page's numbers: forecasts and scores of the last SITE_DAYS days.

    Only daily totals and errors (derived results); no raw document is published.
    """
    rows: dict[str, dict[str, Any]] = {}
    for key in store.list("forecasts/"):
        name = key.rsplit("/", 1)[1]
        if not name.endswith(".json") or "_rerun_" in name:
            continue
        fc = json.loads(store.read(key))
        rows[fc["target_date"]] = {
            "date": fc["target_date"],
            "forecast_mwh": fc["forecast_mwh"],
            "b0_mwh": fc["reference_mwh"],
            "issued_at_art": fc.get("run_at_art"),
            "late": fc.get("late"),
        }
    for key in store.list("scores/"):
        sc = json.loads(store.read(key))
        if sc["target_date"] in rows:
            row = rows[sc["target_date"]]
            for k in (
                "b1_mwh",
                "provisional_mwh",
                "definitive_mwh",
                "forecast_error_pct_provisional",
                "forecast_error_pct_definitive",
                "b1_error_pct_provisional",
                "b1_error_pct_definitive",
                "b0_error_pct_provisional",
                "b0_error_pct_definitive",
            ):
                row[k] = sc.get(k)
    days = sorted(rows)[-SITE_DAYS:]
    recent = [rows[d] for d in days]
    summary: dict[str, Any] = {}
    for kind in ("provisional", "definitive"):
        scored = [r for r in recent if r.get(f"forecast_error_pct_{kind}") is not None]
        summary[kind] = {
            "days": len(scored),
            "mape_model_pct": _mape([r[f"forecast_error_pct_{kind}"] for r in scored]),
            "mape_b1_pct": _mape([r.get(f"b1_error_pct_{kind}") for r in scored]),
            "mape_b0_pct": _mape([r.get(f"b0_error_pct_{kind}") for r in scored]),
        }
    best = []
    for r in recent:
        kind = (
            "definitive"
            if r.get("forecast_error_pct_definitive") is not None
            else "provisional"
        )
        # Model and operator are compared on the same days only.
        if (
            r.get(f"forecast_error_pct_{kind}") is not None
            and r.get(f"b1_error_pct_{kind}") is not None
        ):
            best.append((kind, r))
    summary["best"] = {
        "days": len(best),
        "definitive_days": sum(k == "definitive" for k, _ in best),
        "mape_model_pct": _mape([r[f"forecast_error_pct_{k}"] for k, r in best]),
        "mape_b1_pct": _mape([r.get(f"b1_error_pct_{k}") for k, r in best]),
        "mape_b0_pct": _mape([r.get(f"b0_error_pct_{k}") for k, r in best]),
    }
    champion = (
        json.loads(store.read(CHAMPION))["version"] if store.exists(CHAMPION) else None
    )
    return {
        "generated_at_art": now.isoformat(timespec="seconds"),
        "model_version": champion,
        "days": recent,
        "summary": summary,
    }


def publish_site(store: Store, site: Store, now: dt.datetime) -> int:
    data = site_data(store, now)
    site.write(SITE_DATA, _json(data))
    return len(data["days"])


def daily(
    store: Store,
    run_at: dt.datetime,
    fetch: Fetch = http_get,
    site: Store | None = None,
) -> dict[str, Any]:
    """Daily event: state, weather, forecast of tomorrow, scores, public page data."""
    today = run_at.date()
    out: dict[str, Any] = {"run_at_art": run_at.isoformat(timespec="seconds")}
    out["state"] = update_state(store, today)
    out["weather_days_added"] = update_weather(store, today, fetch)
    error: Exception | None = None
    try:
        out["forecast"] = forecast(store, today + dt.timedelta(days=1), run_at)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        error = exc
        out["forecast_error"] = str(exc)
    out["scores_written"] = score(store)
    if site is not None:
        out["site_days"] = publish_site(store, site, run_at)
    if error is not None:
        raise RuntimeError(f"no forecast: {error}") from error
    return out


# --- monthly ------------------------------------------------------------------------


def update_sintesis(store: Store, today: dt.date, fetch: Fetch) -> list[str]:
    """Download the Síntesis bases listed on this and last year's pages, if missing."""
    known = dict(BASES)
    for year in (today.year - 1, today.year):
        html = fetch(YEAR_PAGE.format(year=year)).decode("utf-8", "replace")
        known.update(find_bases(html))
    added = []
    for base, path in sorted(known.items()):
        key = f"{RAW}sintesis/base_informe_mensual_{base}.zip"
        if not store.exists(key):
            store.write(key, fetch(SITE + path))
            added.append(base)
    return added


def monthly(
    store: Store, run_at: dt.datetime, fetch: Fetch = http_get
) -> dict[str, Any]:
    """Monthly event: Síntesis, supply table, feature table, retrain, new champion."""
    today = run_at.date()
    out: dict[str, Any] = {"new_bases": update_sintesis(store, today, fetch)}
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for key in store.list(f"{RAW}sintesis/"):
            if key.endswith(".zip"):
                dest = tmp / "sintesis" / key.rsplit("/", 1)[1]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(store.read(key))
        supply = build_supply(tmp)
    write_parquet(store, STATE["d7"], supply)
    t_ = _tables(store)
    days = [
        FIRST_DAY + dt.timedelta(days=k) for k in range((today - FIRST_DAY).days + 1)
    ]
    table = build_feature_table(
        definitive_daily(t_["postop"], t_["supply"]),
        valid_versions(t_["postop"], t_["b1"]),
        t_["b1"],
        {"gfs": t_["gfs"]},
        _weights(),
        days,
    )
    write_parquet(store, STATE["features"], table)
    model, meta = train(table, today)
    with tempfile.TemporaryDirectory() as t:
        folder = save(model, meta, Path(t))
        for name in ("model.joblib", "meta.json"):
            store.write(f"models/{meta.version}/{name}", (folder / name).read_bytes())
    store.write(CHAMPION, _json({"version": meta.version}))
    out["model"] = {
        "version": meta.version,
        "n_train": meta.n_train,
        "train_last": meta.train_last,
    }
    return out
