"""Build tabular datasets from the archived CAMMESA documents.

Every published version is kept, with its publication date and time, so that the
version rules (SPEC 2.2) can be applied downstream without re-reading the zips.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from sadi_forecast.parsing import (
    N_HOURS,
    parse_programme_csv,
    parse_programme_txt,
    parse_weekly_area,
    programme_target_date,
)

log = logging.getLogger(__name__)

WEEKLY = "PARTE_SEMANAL_UNIF"
PROGRAMME = "PROGRAMACION_DIARIA"
HOUR_COLS = [f"h{k:02d}" for k in range(1, N_HOURS + 1)]
_AREA_MEMBER_RE = re.compile(r"se\d\darea\.dem", re.IGNORECASE)


def load_doc_index(raw_dir: Path, nemo: str) -> dict[str, dict[str, str]]:
    """Map document id to listing metadata (fecha, hora, version)."""
    index: dict[str, dict[str, str]] = {}
    for path in sorted((raw_dir / "docs_index" / nemo).rglob("*.json")):
        if path.name.endswith(".error.json"):
            continue
        for doc in json.loads(path.read_bytes()):
            index[str(doc["id"])] = {
                "fecha": str(doc.get("fecha", "")),
                "hora": str(doc.get("hora") or ""),
                "version": str(doc.get("version") or ""),
            }
    return index


def _iter_zips(raw_dir: Path, nemo: str) -> Iterator[tuple[dt.date, str, Path]]:
    """(publication folder date, document id, path) for every archived zip."""
    for folder in sorted((raw_dir / "docs" / nemo).iterdir()):
        if not folder.is_dir():
            continue
        pub = dt.date.fromisoformat(folder.name)
        for path in sorted(folder.glob("*.zip")):
            yield pub, path.name.split("_", 1)[0], path


def _publication_time(index: dict[str, dict[str, str]], doc_id: str) -> str:
    return index.get(doc_id, {}).get("hora", "")


def build_weekly_area(raw_dir: Path) -> pd.DataFrame:
    """One row per (document version, date, area) from every SEwwarea.dem member."""
    index = load_doc_index(raw_dir, WEEKLY)
    records: list[dict[str, object]] = []
    for pub, doc_id, path in _iter_zips(raw_dir, WEEKLY):
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            log.warning("bad zip skipped: %s", path)
            continue
        members = [n for n in archive.namelist() if _AREA_MEMBER_RE.fullmatch(n)]
        for member in members:
            try:
                rows = parse_weekly_area(archive.read(member).decode("latin1"))
            except ValueError as exc:
                log.warning("unparseable %s in %s: %s", member, path.name, exc)
                continue
            for r in rows:
                rec: dict[str, object] = {
                    "pub_date": pub,
                    "pub_time": _publication_time(index, doc_id),
                    "doc_id": doc_id,
                    "file": path.name.split("_", 1)[-1],
                    "date": r.date,
                    "area": r.area,
                    "flag": r.flag,
                    "missing": r.hourly is None,
                    "energy_mwh": r.energy_mwh,
                }
                hours = r.hourly or (None,) * N_HOURS
                rec.update(dict(zip(HOUR_COLS, hours, strict=True)))
                records.append(rec)
    return pd.DataFrame.from_records(records)


def build_programme(raw_dir: Path) -> pd.DataFrame:
    """National programmed demand: one row per (version, target day, source format)."""
    index = load_doc_index(raw_dir, PROGRAMME)
    records: list[dict[str, object]] = []
    for pub, doc_id, path in _iter_zips(raw_dir, PROGRAMME):
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            log.warning("bad zip skipped: %s", path)
            continue
        names = {n.lower(): n for n in archive.namelist()}
        days = []
        try:
            if "balance.txt" in names:
                days.append(
                    parse_programme_txt(
                        archive.read(names["balance.txt"]).decode("latin1")
                    )
                )
            if "balance.csv" in names:
                text = archive.read(names["balance.csv"]).decode("utf-8-sig")
                days.append(parse_programme_csv(text, programme_target_date(path.name)))
        except ValueError as exc:
            log.warning("unparseable programme %s: %s", path.name, exc)
            continue
        for d in days:
            rec: dict[str, object] = {
                "pub_date": pub,
                "pub_time": _publication_time(index, doc_id),
                "doc_id": doc_id,
                "file": path.name.split("_", 1)[-1],
                "target_date": d.target_date,
                "source": d.source,
                "energy_mwh": d.energy_mwh,
            }
            rec.update(dict(zip(HOUR_COLS, d.hourly, strict=True)))
            records.append(rec)
    return pd.DataFrame.from_records(records)


def load_daily_history(path: Path) -> pd.DataFrame:
    """D1 daily file (xlsx or its zip): date, gross energy (MWh), peak (MW)."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            member = next(n for n in z.namelist() if n.lower().endswith(".xlsx"))
            data = io.BytesIO(z.read(member))
    else:
        data = io.BytesIO(path.read_bytes())
    raw = pd.read_excel(data, sheet_name=0, header=5, usecols=range(14))
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw.iloc[:, 5], errors="coerce").dt.date,
            "gross_energy_mwh": pd.to_numeric(raw.iloc[:, 9], errors="coerce") * 1000,
            "peak_mw": pd.to_numeric(raw.iloc[:, 10], errors="coerce"),
            "day_type": raw.iloc[:, 6],
        }
    )
    return out.dropna(subset=["date"]).reset_index(drop=True)
