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
# Region headers that close the national ("SIN") block of balance.txt.
_REGION_HEADERS = {
    "GBA",
    "COM",
    "BAS",
    "NOA",
    "CEN",
    "CUY",
    "NEA",
    "CTMSG",
    "LIT",
    "PAT",
}


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
    # Printed daily total minus the sum of the hours (txt only). Rounding gives
    # |x| <= 12; larger values are source inconsistencies, kept and flagged.
    total_mismatch_mwh: float = 0.0
    # Other national components, hourly MWh; None when the line is absent or unreadable.
    losses: tuple[float, ...] | None = None
    pumping: tuple[float, ...] | None = None
    exports: tuple[float, ...] | None = None

    @property
    def total_hourly(self) -> tuple[float, ...] | None:
        """Net demand + losses + pumping (the B1 total; exports excluded)."""
        if self.losses is None or self.pumping is None:
            return None
        return tuple(
            n + lo + pu
            for n, lo, pu in zip(self.hourly, self.losses, self.pumping, strict=True)
        )

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


def _hours_and_total(line: str) -> tuple[float, ...] | None:
    """The last 25 fields of a balance.txt line (24 hours + total), if numeric."""
    fields = line.split()[-(N_HOURS + 1) :]
    try:
        values = tuple(float(x) for x in fields)
    except ValueError:
        return None
    return values if len(values) == N_HOURS + 1 else None


def parse_programme_txt(text: str) -> ProgrammeDay:
    """National ("SIN" block) programme from balance.txt.

    Net demand (required), losses, pumping and the sum of the "EXP." export lines.
    The SIN block ends at the first region header.
    """
    m = _DEL_DIA_RE.search(text)
    if m is None:
        raise ValueError("balance.txt: target day header not found")
    target = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    in_sin = False
    net: tuple[float, ...] | None = None
    parts: dict[str, tuple[float, ...] | None] = {}
    exports = [0.0] * N_HOURS
    for line in text.splitlines():
        if line.strip() == "SIN":
            in_sin = True
            continue
        if not in_sin:
            continue
        if line.strip() in _REGION_HEADERS:
            break
        if line.startswith("DEMANDA NETA"):
            net = tuple(float(x) for x in line[len("DEMANDA NETA") :].split())
            if len(net) != N_HOURS + 1:
                raise ValueError(f"balance.txt: expected 25 values, got {len(net)}")
        elif line.startswith("DEMANDA BOMBEO"):
            parts["pumping"] = _hours_and_total(line)
        elif line.startswith("PERDIDAS"):
            parts["losses"] = _hours_and_total(line)
        elif line.startswith("EXP."):
            values = _hours_and_total(line)
            if values is None:
                raise ValueError(f"balance.txt: unreadable export line {line[:20]!r}")
            exports = [e + v for e, v in zip(exports, values[:N_HOURS], strict=True)]
    if net is None:
        raise ValueError("balance.txt: SIN DEMANDA NETA line not found")
    hourly, total = net[:N_HOURS], net[N_HOURS]
    losses = parts.get("losses")
    # No pumping line means no pumping programmed; an unreadable line means unknown.
    pumping = parts["pumping"] if "pumping" in parts else (0.0,) * (N_HOURS + 1)
    return ProgrammeDay(
        target_date=target,
        hourly=hourly,
        source="txt",
        total_mismatch_mwh=total - sum(hourly),
        losses=None if losses is None else losses[:N_HOURS],
        pumping=None if pumping is None else pumping[:N_HOURS],
        exports=tuple(exports),
    )


def parse_programme_csv(text: str, target_date: dt.date) -> ProgrammeDay:
    """National programmed net demand from BALANCE.csv.

    Sum of the regional 'Demanda Neta' rows.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    sums = {
        name: [0.0] * N_HOURS
        for name in ("demanda neta", "perdidas", "bombeo", "exportacion")
    }
    n_regions = 0
    for raw in reader:
        # Some files use lower-case headers; compare keys and labels case-insensitively.
        row = {k.strip().upper(): (v or "").strip() for k, v in raw.items() if k}
        variable = row.get("VARIABLE", "").lower()
        if row.get("TIPO", "").upper() == "D" and variable in sums:
            target = sums[variable]
            for k in range(N_HOURS):
                target[k] += float(row[f"H{k + 1:02d}"])
            n_regions += variable == "demanda neta"
    if n_regions == 0:
        raise ValueError("BALANCE.csv: no 'Demanda Neta' rows")
    # Absent rows mean zero (e.g. no pumping or no exports programmed that day).
    return ProgrammeDay(
        target_date=target_date,
        hourly=tuple(sums["demanda neta"]),
        source="csv",
        losses=tuple(sums["perdidas"]),
        pumping=tuple(sums["bombeo"]),
        exports=tuple(sums["exportacion"]),
    )
