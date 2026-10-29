"""Parsers for CAMMESA Informe Síntesis Mensual base packages (D7).

Two hourly sheets are read, both with a header row that starts with AÑO and contains
FECHA and HORA (HORA = 1..24, hour ending, Argentina time):
- demand by type (national): "Demanda Horaria por Tipo.xlsx" (2022-12 base onward) or
  sheet DEMANDA of "Base de datos Horaria-Diaria <base>.xlsx" (2021-12 base);
- demand by province: "Demanda Horaria por Provincia.xlsx" (2022-12 base onward).
Every base package is kept, labelled by its base month ("2022-12").
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import re
import unicodedata
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook

log = logging.getLogger(__name__)

TYPE_MEMBER_RE = re.compile(r"(horaria por tipo|horaria-diaria)[^/]*\.xlsx$", re.I)
PROVINCE_MEMBER_RE = re.compile(r"horaria por provincia[^/]*\.xlsx$", re.I)
BASE_RE = re.compile(r"base_informe_mensual_(\d{4}-\d{2})\.zip$", re.I)
EXCEL_EPOCH = dt.date(1899, 12, 30)
HEADER_SEARCH_ROWS = 15

# Output column -> header must contain this text (normalized: lower case, no accents).
TYPE_COLUMNS: dict[str, str] = {
    "gu_mem_mwh": "gran usuario",
    "distributor_mwh": "distribuidor",
    "local_mwh": "demanda local",
    "export_mwh": "exportacion",
    "pumping_mwh": "bombeo",
    "losses_mwh": "perdidas",
    "total_mwh": "demanda total",
}
# From the 2024-12 base the sheet has only GU MEM, distributor and local demand.
REQUIRED_TYPE_COLUMNS = ("local_mwh",)


def normalize(text: object) -> str:
    """Lower case, accents removed, single spaces."""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def to_date(value: object) -> dt.date | None:
    """Excel cell value (datetime or serial number) to a date."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return EXCEL_EPOCH + dt.timedelta(days=int(value))
    return None


def _find_header(rows: list[tuple[Any, ...]]) -> int:
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        cells = {normalize(c) for c in row if c is not None}
        if {"fecha", "hora"} <= cells:
            return i
    raise ValueError("header row with FECHA and HORA not found")


def _pick_sheet(names: Iterable[str]) -> str:
    names = list(names)
    for n in names:
        if "demanda" in normalize(n):
            return n
    return names[0]


def _read_rows(data: bytes) -> list[tuple[Any, ...]]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb[_pick_sheet(wb.sheetnames)]
        return [tuple(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _data_rows(
    rows: list[tuple[Any, ...]],
) -> tuple[list[str], int, int, Iterator[tuple[dt.date, int, tuple[Any, ...]]]]:
    h = _find_header(rows)
    header = [normalize(c) if c is not None else "" for c in rows[h]]
    i_date, i_hour = header.index("fecha"), header.index("hora")

    def gen() -> Iterator[tuple[dt.date, int, tuple[Any, ...]]]:
        for row in rows[h + 1 :]:
            if len(row) <= max(i_date, i_hour):
                continue
            date, hour = to_date(row[i_date]), row[i_hour]
            if date is None or not isinstance(hour, int | float):
                continue
            yield date, int(hour), row

    return header, i_date, i_hour, gen()


def _num(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def parse_type_sheet(data: bytes) -> pd.DataFrame:
    """National hourly demand by type: date, hour, *_mwh columns of TYPE_COLUMNS."""
    header, _, _, rows = _data_rows(_read_rows(data))
    cols: dict[str, int] = {}
    for key, needle in TYPE_COLUMNS.items():
        hits = [i for i, h in enumerate(header) if needle in h]
        if hits:
            cols[key] = hits[0]
    missing = [c for c in REQUIRED_TYPE_COLUMNS if c not in cols]
    if missing:
        raise ValueError(f"columns {missing} not found in header {header}")
    records = [
        {"date": d, "hour": hr, **{k: _num(row[i]) for k, i in cols.items()}}
        for d, hr, row in rows
    ]
    return pd.DataFrame.from_records(records)


def parse_province_sheet(data: bytes) -> pd.DataFrame:
    """Hourly demand by province, long format: date, hour, province, mwh."""
    header, _, i_hour, rows = _data_rows(_read_rows(data))
    provinces = {i: h for i, h in enumerate(header) if i > i_hour and h}
    records = [
        {"date": d, "hour": hr, "province": name, "mwh": _num(row[i])}
        for d, hr, row in rows
        for i, name in provinces.items()
        if i < len(row)
    ]
    return pd.DataFrame.from_records(records)


def _members(archive: zipfile.ZipFile) -> Iterator[tuple[str, bytes]]:
    """xlsx members, descending into nested zips."""
    for name in archive.namelist():
        low = name.lower()
        if low.endswith(".xlsx"):
            yield name, archive.read(name)
        elif low.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive.read(name))) as inner:
                yield from _members(inner)


def build_sintesis(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(by type, by province) for every base zip in raw_dir/sintesis, column base."""
    by_type: list[pd.DataFrame] = []
    by_prov: list[pd.DataFrame] = []
    for path in sorted((raw_dir / "sintesis").glob("*.zip")):
        m = BASE_RE.search(path.name)
        if m is None:
            continue
        base = m.group(1)
        # Some packages also contain a nested copy of themselves (2023-12): the
        # first match of each sheet is used.
        with zipfile.ZipFile(path) as archive:
            found = False
            found_prov = False
            for name, data in _members(archive):
                leaf = name.rsplit("/", 1)[-1]
                if not found and TYPE_MEMBER_RE.search(leaf):
                    by_type.append(parse_type_sheet(data).assign(base=base))
                    found = True
                elif not found_prov and PROVINCE_MEMBER_RE.search(leaf):
                    by_prov.append(parse_province_sheet(data).assign(base=base))
                    found_prov = True
            if not found:
                log.warning("no hourly demand-by-type sheet in %s", path.name)
    empty = pd.DataFrame()
    return (
        pd.concat(by_type, ignore_index=True) if by_type else empty,
        pd.concat(by_prov, ignore_index=True) if by_prov else empty,
    )


def daily_by_base(hourly: pd.DataFrame) -> pd.DataFrame:
    """Daily sums per (base, date); NaN unless all 24 hours are present."""
    value_cols = [c for c in hourly.columns if c.endswith("_mwh")]
    grp = hourly.groupby(["base", "date"])
    out = grp[value_cols].sum(min_count=1)
    out["n_hours"] = grp["hour"].nunique()
    out.loc[out["n_hours"] != 24, value_cols] = float("nan")
    return out.reset_index()


def latest_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """Per date, the complete day from the latest base that contains it."""
    days = daily_by_base(hourly).dropna(subset=["local_mwh"])
    return (
        days.sort_values(["date", "base"])
        .groupby("date")
        .tail(1)
        .reset_index(drop=True)
    )


SUPPLY_MEMBER_RE = re.compile(r"^oferta total horaria\.xlsx$", re.I)
IMPEXP_MEMBER_RE = re.compile(r"^import-export horaria\.xlsx$", re.I)
# Supply columns by name; older bases group technologies (2021-12: OFERTA sheet).
SUPPLY_NAMES = {
    "nuclear",
    "biogas",
    "biomasa",
    "eolica",
    "hidraulica > 50",
    "hidraulica < 50",
    "solar",
    "ciclos combinados",
    "motor diesel",
    "turbina a gas",
    "turbovapor",
    "importacion",
    "termica",
    "hidraulica",
    "renovable",
}


def supply_columns(header: list[str], i_hour: int) -> list[int]:
    """Indices of the supply columns (generation by technology + imports).

    In the 2023-12 base the import column has an empty header right after
    "turbovapor" and a TOTAL column follows; totals are never included.
    """
    cols = [i for i, h in enumerate(header) if i > i_hour and h in SUPPLY_NAMES]
    if "importacion" not in header and "turbovapor" in header:
        nxt = header.index("turbovapor") + 1
        if nxt < len(header) and header[nxt] == "":
            cols.append(nxt)
    if not cols:
        raise ValueError(f"no supply columns in header {header}")
    return cols


def _sheet_values(
    data: bytes, sheet: str | None, pick: str
) -> dict[tuple[dt.date, int], float]:
    """(date, hour) -> value; pick = 'supply' or 'exports'."""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    header, _, i_hour, it = _data_rows(rows)
    if pick == "supply":
        cols = supply_columns(header, i_hour)
    else:
        cols = [i for i, h in enumerate(header) if h.startswith("exportacion")]
        if len(cols) != 1:
            raise ValueError(f"export column not found in header {header}")
    out: dict[tuple[dt.date, int], float] = {}
    for d, hr, row in it:
        values = [_num(row[i]) for i in cols if i < len(row)]
        # An hour with no value in any column is missing (NaN), not zero.
        present = [v for v in values if v is not None]
        out[(d, hr)] = sum(present) if present else float("nan")
    return out


def build_supply(raw_dir: Path) -> pd.DataFrame:
    """Hourly supply and exports per base: base, date, hour, supply_mwh, export_mwh."""
    frames: list[pd.DataFrame] = []
    for path in sorted((raw_dir / "sintesis").glob("*.zip")):
        m = BASE_RE.search(path.name)
        if m is None:
            continue
        supply: dict[tuple[dt.date, int], float] | None = None
        exports: dict[tuple[dt.date, int], float] | None = None
        with zipfile.ZipFile(path) as archive:
            for name, data in _members(archive):
                leaf = name.rsplit("/", 1)[-1]
                if supply is None and SUPPLY_MEMBER_RE.search(leaf):
                    supply = _sheet_values(data, None, "supply")
                elif exports is None and IMPEXP_MEMBER_RE.search(leaf):
                    exports = _sheet_values(data, None, "exports")
                elif supply is None and "horaria-diaria" in leaf.lower():
                    supply = _sheet_values(data, "OFERTA", "supply")
                    exports = _sheet_values(data, "DEMANDA", "exports")
        if supply is None or exports is None:
            log.warning("supply or exports sheet missing in %s", path.name)
            continue
        frames.append(
            pd.DataFrame(
                [
                    (m.group(1), d, h, v, exports.get((d, h)))
                    for (d, h), v in supply.items()
                ],
                columns=["base", "date", "hour", "supply_mwh", "export_mwh"],
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
