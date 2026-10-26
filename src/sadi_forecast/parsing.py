"""Parsers for CAMMESA published documents.

D5 Parte Semanal, member SEwwarea.dem: hourly demand by area (fixed-width text).
D6 Programación Diaria: day-ahead programme; balance.txt (2010 → 2024-11) or
BALANCE.csv (2024-10 →).

Rules are documented in docs/data_inventory.md. Parsers are pure functions on text;
reading zips and choosing versions happen elsewhere.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass

N_HOURS = 24
AREA_FIELD_START = 8  # SEwwarea.dem: first hourly field starts at column 8
AREA_FIELD_WIDTH = 8

_PERIOD_RE = re.compile(
    r"Periodo\s*:\s*(\d\d)/(\d\d)/(\d\d)\s+al\s+(\d\d)/(\d\d)/(\d\d)"
)
_DAY_ROW_RE = re.compile(r"^(\d\d)/(\d\d) ([A-Z ])")
_SECTION_RE = re.compile(r"^[A-Z][A-Z ]{3,}")
_PD_NAME_RE = re.compile(r"PD(\d\d)(\d\d)(\d\d)", re.IGNORECASE)
_DEL_DIA_RE = re.compile(r"DEL DIA\s+(\d{1,2})/(\d\d)/(\d{4})")


@dataclass(frozen=True)
class AreaDay:
    """One area-day row of SEwwarea.dem.

    `flag` is the row marker (A, S, E; meaning pending CAMMESA's answer). An empty flag
    marks a missing row: CAMMESA fills it with zeros, so `hourly` is None. `hourly` is
    also None when a field overflowed ("********").
    """

    date: dt.date
    area: str
    flag: str
    hourly: tuple[float, ...] | None

    @property
    def energy_mwh(self) -> float | None:
        return None if self.hourly is None else sum(self.hourly)


@dataclass(frozen=True)
class ProgrammeDay:
    """National programmed net demand for one target day (MWh per hour, hours 1-24)."""

    target_date: dt.date
    hourly: tuple[float, ...]
    source: str  # "txt" or "csv"

    @property
    def energy_mwh(self) -> float:
        return sum(self.hourly)


def _period(text: str) -> tuple[dt.date, dt.date]:
    m = _PERIOD_RE.search(text)
    if m is None:
        raise ValueError("SEwwarea.dem: period header not found")
    d0, m0, y0, d1, m1, y1 = (int(x) for x in m.groups())
    return dt.date(2000 + y0, m0, d0), dt.date(2000 + y1, m1, d1)


def _date_in_period(day: int, month: int, start: dt.date, end: dt.date) -> dt.date:
    for year in (start.year, end.year):
        candidate = dt.date(year, month, day)
        if start <= candidate <= end:
            return candidate
    raise ValueError(f"day {day:02d}/{month:02d} outside period {start} → {end}")


def _area_fields(line: str) -> list[str]:
    return [
        line[
            AREA_FIELD_START + AREA_FIELD_WIDTH * k : AREA_FIELD_START
            + AREA_FIELD_WIDTH * (k + 1)
        ]
        for k in range(N_HOURS)
    ]


def parse_weekly_area(text: str) -> list[AreaDay]:
    """Area-level day rows of a SEwwarea.dem file.

    Sub-sections and jurisdictions are excluded.
    """
    start, end = _period(text)
    rows: list[AreaDay] = []
    area: str | None = None
    for line in text.splitlines():
        if line.startswith("AREA "):
            area = line[5:].strip()
            continue
        if line.startswith("Total") or _SECTION_RE.match(line):
            # "Total :" closes the block; any other header opens another section
            area = None
            continue
        m = _DAY_ROW_RE.match(line)
        if m is None or area is None:
            continue
        date = _date_in_period(int(m.group(1)), int(m.group(2)), start, end)
        flag = m.group(3).strip()
        fields = _area_fields(line)
        unreadable = any("*" in f or not f.strip() for f in fields)
        hourly = None if unreadable or not flag else tuple(float(f) for f in fields)
        rows.append(AreaDay(date=date, area=area, flag=flag, hourly=hourly))
    return rows


def programme_target_date(file_name: str) -> dt.date:
    """Target day encoded in a Programación Diaria file name (PDyymmdd)."""
    m = _PD_NAME_RE.search(file_name)
    if m is None:
        raise ValueError(f"not a programme file name: {file_name}")
    yy, mm, dd = (int(x) for x in m.groups())
    return dt.date(2000 + yy, mm, dd)


def parse_programme_txt(text: str) -> ProgrammeDay:
    """National ("SIN" block) programmed net demand from balance.txt."""
    m = _DEL_DIA_RE.search(text)
    if m is None:
        raise ValueError("balance.txt: target day header not found")
    target = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    in_sin = False
    for line in text.splitlines():
        if line.strip() == "SIN":
            in_sin = True
            continue
        if in_sin and line.startswith("DEMANDA NETA"):
            values = [float(x) for x in line[len("DEMANDA NETA") :].split()]
            if len(values) != N_HOURS + 1:
                raise ValueError(f"balance.txt: expected 25 values, got {len(values)}")
            hourly, total = tuple(values[:N_HOURS]), values[N_HOURS]
            if (
                abs(sum(hourly) - total) > N_HOURS / 2
            ):  # 24 integers rounded: |error| ≤ 12
                raise ValueError(
                    "balance.txt: hourly values do not add up to the daily total"
                )
            return ProgrammeDay(target_date=target, hourly=hourly, source="txt")
    raise ValueError("balance.txt: SIN DEMANDA NETA line not found")


def parse_programme_csv(text: str, target_date: dt.date) -> ProgrammeDay:
    """National programmed net demand from BALANCE.csv.

    Sum of the regional 'Demanda Neta' rows.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    totals = [0.0] * N_HOURS
    n_regions = 0
    for row in reader:
        if row["TIPO"] == "D" and row["VARIABLE"] == "Demanda Neta":
            for k in range(N_HOURS):
                totals[k] += float(row[f"H{k + 1:02d}"])
            n_regions += 1
    if n_regions == 0:
        raise ValueError("BALANCE.csv: no 'Demanda Neta' rows")
    return ProgrammeDay(target_date=target_date, hourly=tuple(totals), source="csv")
