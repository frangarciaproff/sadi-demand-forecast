"""Parte Post Operativo (D8): hourly supply from the Access database in each zip.

Supply = sum of VALORES_GENERADORES.ENERGIA over all units (imports are units of the
table). CONTROL_VALORES_CC repeats the combined-cycle units and is never added.
Parsing a database takes ~2 s, so results are cached per document (JSON) and the
archive is processed in parallel.

The operating day is taken from the database itself (table FECHA): the operator
sometimes attaches another day's file to a listing entry (24 of 6,926 files
2018-2026, e.g. the file of 2022-06-15 listed as the daily report of 2022-08-15).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import tempfile
import zipfile
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from access_parser import AccessParser

from sadi_forecast.tables import load_doc_index

log = logging.getLogger(__name__)

NEMO = "PARTE_POST_OPERATIVO_UNIF"
DAILY = "PARTE_POST_OPERATIVO"
COMPLEMENT = "PARTE_POST_OPERATIVO_COMP"
N_HOURS = 24
SUPPLY_COLS = [f"s{k:02d}" for k in range(1, N_HOURS + 1)]
CACHE_VERSION = 2


def hourly_supply(mdb_path: Path) -> dict[str, object]:
    """Hourly supply (MWh), operating day and row counts from one database."""
    db = AccessParser(str(mdb_path))
    table = db.parse_table("VALORES_GENERADORES")
    fecha = db.parse_table("FECHA").get("Fecha") or [None]
    hours = [0.0] * N_HOURS
    seen: set[int] = set()
    bad = 0
    for hour, energy in zip(table["HORA"], table["ENERGIA"], strict=True):
        if not isinstance(hour, int) or not 1 <= hour <= N_HOURS:
            bad += 1
            continue
        seen.add(hour)
        hours[hour - 1] += float(energy or 0.0)
    return {
        "hourly": hours,
        "n_rows": len(table["HORA"]),
        "n_units": len(set(table["GRUPO"])),
        "hours_present": len(seen),
        "bad_rows": bad,
        "fecha": str(fecha[0])[:10] if fecha[0] is not None else None,
    }


def parse_zip(path: Path) -> dict[str, object]:
    """Extract the .mdb of one archived zip to a temporary file and parse it."""
    with zipfile.ZipFile(path) as z:
        members = [n for n in z.namelist() if n.lower().endswith(".mdb")]
        if not members:
            raise ValueError(f"no .mdb in {path.name}")
        data = z.read(members[0])
    name_date = _name_date(members[0])
    fd, tmp = tempfile.mkstemp(suffix=".mdb")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        result = hourly_supply(Path(tmp))
    finally:
        os.unlink(tmp)
    result["name_date"] = name_date
    return result


def _name_date(name: str) -> str | None:
    """Operating day encoded in a database name (POyymmdd.mdb)."""
    m = re.search(r"PO(\d\d)(\d\d)(\d\d)", name, re.IGNORECASE)
    if m is None:
        return None
    yy, mm, dd = (int(x) for x in m.groups())
    try:
        return dt.date(2000 + yy, mm, dd).isoformat()
    except ValueError:
        return None


def _iter_archive(raw_dir: Path) -> Iterator[tuple[dt.date, str, Path]]:
    """(operating day, document id, path); folders are named by operating day."""
    root = raw_dir / "docs" / NEMO
    if not root.exists():
        return
    for folder in sorted(root.iterdir()):
        if folder.is_dir():
            day = dt.date.fromisoformat(folder.name)
            for path in sorted(folder.glob("*.zip")):
                yield day, path.name.split("_", 1)[0], path


def _cached(path: Path, cache: Path) -> dict[str, object]:
    target = cache / f"{path.name}.json"
    if target.exists():
        data: dict[str, object] = json.loads(target.read_text(encoding="utf-8"))
        if data.get("cache_version") == CACHE_VERSION:
            return data
    result = {**parse_zip(path), "cache_version": CACHE_VERSION}
    target.write_text(json.dumps(result), encoding="utf-8")
    return result


def build_postop(raw_dir: Path, cache_dir: Path, workers: int = 4) -> pd.DataFrame:
    """One row per archived document: operating day (from the database), listed
    day, kind (daily/complement), publication timestamp, hourly supply s01-s24 and
    supply_mwh."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    index = load_doc_index(raw_dir, NEMO)
    jobs = list(_iter_archive(raw_dir))
    results: dict[Path, dict[str, object]] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_cached, p, cache_dir): p for _, _, p in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            path = futures[fut]
            try:
                results[path] = fut.result()
            except Exception as exc:  # corrupt zip or database: skip, keep going
                log.warning("post operativo skipped: %s (%s)", path.name, exc)
            if i % 500 == 0:
                log.info("post operativo: %d / %d parsed", i, len(jobs))
    records: list[dict[str, object]] = []
    for listed, doc_id, path in jobs:
        res = results.get(path)
        if res is None:
            continue
        meta = index.get(doc_id, {})
        hourly = res["hourly"]
        assert isinstance(hourly, list)
        fecha, name_date = res.get("fecha"), res.get("name_date")
        day = dt.date.fromisoformat(str(fecha)) if fecha else listed
        rec: dict[str, object] = {
            "date": day,
            "listed_date": listed,
            "name_date": name_date,
            "date_mismatch": day != listed,
            "doc_id": doc_id,
            "kind": {DAILY: "daily", COMPLEMENT: "complement"}.get(
                meta.get("nemo", ""), "unknown"
            ),
            "published": meta.get("version", ""),
            "supply_mwh": float(sum(hourly)),
            "hours_present": res["hours_present"],
            "n_units": res["n_units"],
        }
        rec.update(dict(zip(SUPPLY_COLS, hourly, strict=True)))
        records.append(rec)
    return pd.DataFrame.from_records(records)
