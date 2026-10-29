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
from sadi_forecast.hourly import (
    HOURS,
    S_COLS,
    X_COLS,
    align_programme,
    definitive_hourly,
)
from sadi_forecast.hourly import programme_hourly as programme_hourly_table
from sadi_forecast.live_features import GFS_COLUMN, features_for
from sadi_forecast.openmeteo import LIVE_VARS, http_get, live_url
from sadi_forecast.points import POINTS
from sadi_forecast.postop import NEMO as POSTOP_NEMO
from sadi_forecast.postop import build_postop
from sadi_forecast.production import forecast_day, load, save, train
from sadi_forecast.production_hourly import (
    SHAPE_FILE,
    SHAPE_META_FILE,
    design_for_day,
    forecast_hourly,
    load_shape,
    merge_hourly_weather,
    programme_curve,
    save_shape,
    train_shape,
)
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
    "gfs_hourly": "state/gfs_hourly.parquet",
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
    # Only the hourly curve needs gfs_hourly: a failure here must not stop the daily
    # forecast (audit 2026-10-29, v2).
    try:
        old_h = (
            read_parquet(store, STATE["gfs_hourly"])
            if store.exists(STATE["gfs_hourly"])
            else pd.DataFrame()
        )
        hourly = pd.concat(frames, ignore_index=True)
        write_parquet(store, STATE["gfs_hourly"], merge_hourly_weather(hourly, old_h))
    except Exception:
        log.exception("gfs_hourly not updated")
    return len(merged) - len(old)


def issue_fetch_missing_hours(
    store: Store, day: dt.date, weights: pd.Series
) -> int | None:
    """Hours of `day` (ART) for which a point with positive weight has no value in the
    fetch saved at the issue date (day - 1); None if that fetch is not stored.

    The state tables fill such holes from older fetches, which may hold values of a
    different lead time (audit 2026-10-29, v2): the forecast record carries this count.
    """
    issue = (day - dt.timedelta(days=1)).isoformat()
    hours = pd.date_range(dt.datetime.combine(day, dt.time()), periods=24, freq="h")
    missing: set[pd.Timestamp] = set()
    for pt in POINTS:
        if weights.get(pt.key, 0.0) <= 0:
            continue
        key = f"raw/open_meteo/gfs_live/{pt.key}/{issue}.json"
        if not store.exists(key):
            return None
        f = response_frame(json.loads(store.read(key)), pt.key)
        have = set(f.loc[f[GFS_COLUMN].notna(), "time_art"])
        missing.update(h for h in hours if h not in have)
    return len(missing)


# --- daily --------------------------------------------------------------------------


def _tables(store: Store) -> dict[str, Any]:
    d6 = read_parquet(store, STATE["d6"])
    return {
        "postop": _dates(read_parquet(store, STATE["d8"])),
        "supply": _dates(read_parquet(store, STATE["d7"])),
        "d6": d6,
        "b1": b1_daily(d6),
        "gfs": read_parquet(store, STATE["gfs"]),
    }


def _gfs_hourly(store: Store) -> pd.DataFrame:
    if not store.exists(STATE["gfs_hourly"]):
        raise FileNotFoundError(f"{STATE['gfs_hourly']} missing")
    return read_parquet(store, STATE["gfs_hourly"])


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


def _load_champion_shape(store: Store, tmp: Path) -> tuple[Any, Any] | None:
    """The champion's shape model, or None if that version has none."""
    version = json.loads(store.read(CHAMPION))["version"]
    names = (SHAPE_FILE, SHAPE_META_FILE)
    if not all(store.exists(f"models/{version}/{n}") for n in names):
        return None
    folder = tmp / f"{version}_shape"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(store.read(f"models/{version}/{name}"))
    return load_shape(folder)


def _hourly_record(
    store: Store,
    t: dict[str, Any],
    features: pd.DataFrame,
    day: dt.date,
    mwh: float,
    missing_hours: int | None,
) -> dict[str, object]:
    """Hourly curve of `day`, or why it is missing. Any failure is caught: the daily
    forecast is already stored (audit 2026-10-29, v2)."""
    try:
        if missing_hours is None:
            return {"hourly_error": "no weather fetch stored at the issue date"}
        if missing_hours > 0:
            return {
                "hourly_error": f"{missing_hours} hours of the target day missing "
                "in the issue-time weather fetch"
            }
        with tempfile.TemporaryDirectory() as tmp:
            shape = _load_champion_shape(store, Path(tmp))
        if shape is None:
            return {"hourly_error": "no shape model for the champion version"}
        x = design_for_day(
            features, t["postop"], t["d6"], _gfs_hourly(store), _weights(), day
        )
        return forecast_hourly(shape[0], shape[1], x, mwh)
    except Exception as exc:
        log.exception("no hourly curve for %s", day)
        return {"hourly_error": f"{type(exc).__name__}: {exc}"}


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
    missing: int | None = None
    try:
        missing = issue_fetch_missing_hours(store, day, _weights())
    except Exception:
        log.exception("issue-time weather fetch not readable")
    rec.update(
        {
            "issue_time_art": issue.isoformat(),
            "run_at_art": run_at.isoformat(timespec="seconds"),
            "late": run_at > issue,
            "weather": "live",
            "issue_fetch_missing_hours": missing,
        }
    )
    # The daily forecast is stored before the hourly curve is attempted.
    store.write(key, _json(rec))
    daily_mwh = rec["forecast_mwh"]
    assert isinstance(daily_mwh, float)
    rec.update(_hourly_record(store, t, features, day, daily_mwh, missing))
    store.write(key, _json(rec))
    return rec


def _pct(pred: float | None, actual: float | None) -> float | None:
    if pred is None or actual is None or pd.isna(pred) or pd.isna(actual):
        return None
    return round(100 * (pred / actual - 1), 3)


def provisional_actuals(versions: pd.DataFrame) -> pd.DataFrame:
    """Provisional actual per day (SPEC 2.2): the latest version published so far that
    passes the validity check (a later complement replaces the daily report). Invalid
    reports count as missing; a day with none has no provisional actual."""
    return (
        versions[versions["valid"]]
        .sort_values("published_art")
        .groupby("date")
        .tail(1)
        .set_index("date")
    )


def _curve_errors(
    pred: list[float] | None, actual: list[float] | None
) -> dict[str, float | int | None]:
    """Hourly MAPE, daily peak error (%) and peak-hour error (h) of one curve."""
    names = ("hourly_mape_pct", "peak_error_pct", "peak_hour_error_h")
    if (
        not pred
        or not actual
        or len(pred) != 24
        or len(actual) != 24
        or any(pd.isna(v) for v in [*pred, *actual])
        or min(actual) <= 0
    ):
        return dict.fromkeys(names)
    e = [abs(100 * (p / a - 1)) for p, a in zip(pred, actual, strict=True)]
    return {
        "hourly_mape_pct": round(sum(e) / 24, 3),
        "peak_error_pct": round(100 * (max(pred) / max(actual) - 1), 3),
        "peak_hour_error_h": abs(pred.index(max(pred)) - actual.index(max(actual))),
    }


def _hourly_actuals(
    t: dict[str, Any], latest: pd.DataFrame
) -> tuple[dict[dt.date, list[float]], dict[dt.date, list[float]]]:
    """Provisional (latest valid version - programmed exports) and definitive (D7)
    hourly actuals per day."""
    prog = programme_hourly_table(t["d6"])
    exports = prog.reindex(latest.index)[X_COLS].fillna(0.0).to_numpy()
    prov_h = latest[S_COLS].to_numpy(dtype=float) - exports
    prov = {
        d: [float(v) for v in row] for d, row in zip(latest.index, prov_h, strict=True)
    }
    defin_h = definitive_hourly(t["supply"])
    defin = {d: [float(v) for v in defin_h.loc[d, HOURS]] for d in defin_h.index}
    return prov, defin


def _aligned_curve(aligned: pd.DataFrame | None, day: dt.date) -> list[float] | None:
    if aligned is None or day not in aligned.index or aligned.loc[day].isna().any():
        return None
    return [round(float(v), 1) for v in aligned.loc[day, HOURS].to_numpy(dtype=float)]


def _hourly_scores(
    curve: list[float],
    prog: pd.DataFrame,
    aligned: pd.DataFrame | None,
    day: dt.date,
    prov_hourly: dict[dt.date, list[float]],
    defin_hourly: dict[dt.date, list[float]],
) -> dict[str, Any]:
    """Hourly scores of the model and of the operator's programme, as published (the
    pre-registered benchmark) and aligned to D7's hours (b1_aligned)."""
    out: dict[str, Any] = {}
    b1_curve = programme_curve(prog, day)
    b1_aligned = _aligned_curve(aligned, day)
    for actual, table in (("provisional", prov_hourly), ("definitive", defin_hourly)):
        a_curve = table.get(day)
        out[f"{actual}_peak_mw"] = round(max(a_curve), 1) if a_curve else None
        for name, pred in (
            ("forecast", curve),
            ("b1", b1_curve),
            ("b1_aligned", b1_aligned),
        ):
            for k, v in _curve_errors(pred, a_curve).items():
                out[f"{name}_{k}_{actual}"] = v
    return out


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
    latest = provisional_actuals(valid_versions(t["postop"], t["b1"]))
    defin = definitive_daily(t["postop"], t["supply"]).dropna(subset=["target_mwh"])
    target = dict(zip(defin["date"], defin["target_mwh"].astype(float), strict=True))
    b1_rows = t["b1"].dropna(subset=["b1_total_mwh"])
    b1 = dict(
        zip(b1_rows["target_date"], b1_rows["b1_total_mwh"].astype(float), strict=True)
    )
    prov_value = dict(zip(latest.index, latest["value_mwh"].astype(float), strict=True))
    prov_kind = dict(zip(latest.index, latest["kind"].astype(str), strict=True))
    # Hourly scores are optional: a failure leaves the daily scores intact.
    prov_hourly: dict[dt.date, list[float]] = {}
    defin_hourly: dict[dt.date, list[float]] = {}
    prog: pd.DataFrame | None = None
    aligned: pd.DataFrame | None = None
    try:
        prov_hourly, defin_hourly = _hourly_actuals(t, latest)
        prog = programme_hourly_table(t["d6"])
        aligned = align_programme(prog)
    except Exception:
        log.exception("hourly actuals not built; hourly scores skipped")
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
            "provisional_source": prov_kind.get(day),
            "definitive_mwh": definitive,
        }
        if rec["provisional_mwh"] is None and rec["definitive_mwh"] is None:
            continue
        for actual in ("provisional", "definitive"):
            a = rec[f"{actual}_mwh"]
            for name in ("forecast", "b0", "b1"):
                rec[f"{name}_error_pct_{actual}"] = _pct(rec[f"{name}_mwh"], a)
        curve = fc.get("hourly_mwh")
        if curve and prog is not None:
            try:
                rec.update(
                    _hourly_scores(curve, prog, aligned, day, prov_hourly, defin_hourly)
                )
            except Exception:
                log.exception("hourly scores of %s skipped", day)
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
    curves: dict[str, list[float]] = {}
    for key in store.list("forecasts/"):
        name = key.rsplit("/", 1)[1]
        if not name.endswith(".json") or "_rerun_" in name:
            continue
        fc = json.loads(store.read(key))
        if fc.get("hourly_mwh"):
            curves[fc["target_date"]] = fc["hourly_mwh"]
        rows[fc["target_date"]] = {
            "date": fc["target_date"],
            "forecast_mwh": fc["forecast_mwh"],
            "b0_mwh": fc["reference_mwh"],
            "issued_at_art": fc.get("run_at_art"),
            "late": fc.get("late"),
        }
    # The operator's programme for a day is published about 21:30 the evening before,
    # so it is shown as soon as the state has it, before the day is scored.
    prog = None
    if rows and store.exists(STATE["d6"]):
        d6 = read_parquet(store, STATE["d6"])
        try:
            prog = programme_hourly_table(d6)
        except Exception:
            log.exception("hourly programme not read; page shows no operator curve")
        b1 = b1_daily(d6).dropna(subset=["b1_total_mwh"])
        programme = dict(
            zip(
                (d.isoformat() for d in b1["target_date"]),
                b1["b1_total_mwh"].astype(float),
                strict=True,
            )
        )
        for day, row in rows.items():
            row["b1_mwh"] = programme.get(day)
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
                *(
                    f"{who}_hourly_mape_pct_{kind}"
                    for who in ("forecast", "b1", "b1_aligned")
                    for kind in ("provisional", "definitive")
                ),
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
    summary["hourly"], curve = _site_hourly(recent, curves, prog)
    champion = (
        json.loads(store.read(CHAMPION))["version"] if store.exists(CHAMPION) else None
    )
    return {
        "generated_at_art": now.isoformat(timespec="seconds"),
        "model_version": champion,
        "days": recent,
        "summary": summary,
        "curve": curve,
    }


def _site_hourly(
    recent: list[dict[str, Any]],
    curves: dict[str, list[float]],
    prog: pd.DataFrame | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Hourly summary and tomorrow's curve; empty if anything fails (the daily page
    data is published anyway)."""
    empty = {"days": 0, "mape_model_pct": None, "mape_b1_pct": None}
    try:
        return _site_hourly_parts(recent, curves, prog)
    except Exception:
        log.exception("hourly page data skipped")
        return empty, None


def _site_hourly_parts(
    recent: list[dict[str, Any]],
    curves: dict[str, list[float]],
    prog: pd.DataFrame | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    hourly = []
    for r in recent:
        for kind in ("definitive", "provisional"):
            m = r.get(f"forecast_hourly_mape_pct_{kind}")
            b = r.get(f"b1_aligned_hourly_mape_pct_{kind}")
            if m is not None and b is not None:
                hourly.append((m, b))
                break
    summary_hourly = {
        "days": len(hourly),
        "mape_model_pct": _mape([m for m, _ in hourly]),
        "mape_b1_pct": _mape([b for _, b in hourly]),
    }
    curve = None
    if curves:
        day_iso = max(curves)
        values = curves[day_iso]
        day = dt.date.fromisoformat(day_iso)
        b1_curve = programme_curve(prog, day) if prog is not None else None
        b1_aligned = (
            _aligned_curve(align_programme(prog), day) if prog is not None else None
        )
        curve = {
            "date": day_iso,
            "forecast_mwh": values,
            "b1_mwh": b1_curve,
            "b1_aligned_mwh": b1_aligned,
            "peak_mw": max(values),
            "peak_hour": values.index(max(values)) + 1,
        }
    return summary_hourly, curve


def publish_site(store: Store, site: Store, now: dt.datetime) -> int:
    data = site_data(store, now)
    site.write(SITE_DATA, _json(data))
    return len(data["days"])


def evening(store: Store, site: Store | None, run_at: dt.datetime) -> dict[str, Any]:
    """Evening event (after the collector's 23:30 run): add the documents published
    today, including the operator's programme for tomorrow, and refresh the page."""
    out: dict[str, Any] = {"run_at_art": run_at.isoformat(timespec="seconds")}
    out["state"] = update_state(store, run_at.date())
    if site is not None:
        out["site_days"] = publish_site(store, site, run_at)
    return out


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
    # A failed shape model leaves the new version without an hourly curve; the daily
    # model is still promoted.
    try:
        out["shape_model"] = _train_and_store_shape(store, table, t_, today)
    except Exception as exc:
        log.exception("shape model not trained")
        out["shape_model_error"] = f"{type(exc).__name__}: {exc}"
    store.write(CHAMPION, _json({"version": meta.version}))
    out["model"] = {
        "version": meta.version,
        "n_train": meta.n_train,
        "train_last": meta.train_last,
    }
    return out


def _train_and_store_shape(
    store: Store, table: pd.DataFrame, t: dict[str, Any], as_of: dt.date
) -> dict[str, Any]:
    model, meta = train_shape(
        table, t["postop"], t["d6"], t["supply"], _gfs_hourly(store), _weights(), as_of
    )
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        save_shape(model, meta, folder)
        for name in (SHAPE_FILE, SHAPE_META_FILE):
            store.write(f"models/{meta.version}/{name}", (folder / name).read_bytes())
    return {
        "version": meta.version,
        "n_days": meta.n_days,
        "train_last": meta.train_last,
    }


def shape(store: Store) -> dict[str, Any]:
    """Train the shape model for the current champion version (same as_of date), from
    the stored feature table; used once to add v2 to a v1 model already trained."""
    version = dt.date.fromisoformat(json.loads(store.read(CHAMPION))["version"])
    table = read_parquet(store, STATE["features"])
    return _train_and_store_shape(store, table, _tables(store), version)
