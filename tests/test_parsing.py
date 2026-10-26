"""Parsers on synthetic fragments reproducing each format quirk.

No CAMMESA data is stored in the repository.
"""

from __future__ import annotations

import datetime as dt

import pytest

from sadi_forecast.parsing import (
    parse_programme_csv,
    parse_programme_txt,
    parse_weekly_area,
    programme_target_date,
)


def _row(date: str, flag: str, values: list[str]) -> str:
    # Real layout: "dd/mm F " then 24 right-aligned 8-character fields from column 8
    tail = "   9999.999  0.0  0.0  0.0  0.0 21:00"
    return f"{date} {flag} " + "".join(v.rjust(8) for v in values) + tail


HOURS = [f"{100 + k:.2f}" for k in range(24)]

WEEK = "\n".join(
    [
        "C.A.M.M.E.S.A.     P A R T E   P R O V I S O R I O   Semana  : 01",
        "GPyCP   DEMANDAS POR AREA EN MWh   Periodo : 29/12/25   al 04/01/26",
        "            H01     H02",
        "AREA GBA",
        _row("29/12", "A", HOURS),
        _row("30/12", "S", HOURS),
        "",
        "Total :  999.9",
        "COMPRA SPOT DE GENERADORES",
        _row("29/12", "S", ["1.00"] * 24),
        "Total :  24.0",
        "JURISDICCION EDENOR",
        _row("29/12", "A", ["50.00"] * 24),
        "AREA CENTRO",
        _row(
            "01/01", "A", ["10045.50"] + ["9651.37"] * 23
        ),  # 8-character values glue together
        _row("02/01", "E", ["********"] + ["1.00"] * 23),  # overflow field
        _row("03/01", " ", ["0.00"] * 24),  # no marker: missing row filled with zeros
    ]
)


def test_weekly_area_keeps_only_area_rows() -> None:
    rows = parse_weekly_area(WEEK)
    assert [(r.area, r.date) for r in rows] == [
        ("GBA", dt.date(2025, 12, 29)),
        ("GBA", dt.date(2025, 12, 30)),
        ("CENTRO", dt.date(2026, 1, 1)),
        ("CENTRO", dt.date(2026, 1, 2)),
        ("CENTRO", dt.date(2026, 1, 3)),
    ]


def test_weekly_area_values_flags_and_year_boundary() -> None:
    gba, _, centro, overflow, missing = parse_weekly_area(WEEK)
    assert gba.flag == "A"
    assert gba.energy_mwh == pytest.approx(sum(float(v) for v in HOURS))
    assert centro.hourly is not None
    assert centro.hourly[0] == pytest.approx(10045.50)
    assert centro.hourly[1] == pytest.approx(9651.37)
    assert overflow.flag == "E"
    assert overflow.hourly is None
    assert overflow.energy_mwh is None
    assert missing.flag == ""
    assert missing.hourly is None


def test_weekly_area_requires_period() -> None:
    with pytest.raises(ValueError, match="period"):
        parse_weekly_area("AREA GBA\n")


def _balance_txt(values: list[int]) -> str:
    total = sum(values)
    return "\n".join(
        [
            "CAMMESA                                        Fecha:  5/01/2010",
            "BALANCE POR AREA DISCRIMINADO POR GRUPOS              DEL DIA   6/01/2010",
            "SIN",
            "DEMANDA NETA"
            + " " * 30
            + "".join(str(v).rjust(7) for v in values)
            + str(total).rjust(7),
            "DEMANDA BOMBEO      0      0",
            "GBA",
            "DEMANDA NETA"
            + " " * 30
            + "".join("1".rjust(7) for _ in values)
            + "24".rjust(7),
        ]
    )


def test_programme_txt_reads_national_block() -> None:
    values = [15000 + k for k in range(24)]
    day = parse_programme_txt(_balance_txt(values))
    assert day.target_date == dt.date(2010, 1, 6)
    assert day.hourly == tuple(float(v) for v in values)
    assert day.source == "txt"


def test_programme_txt_checks_total() -> None:
    text = _balance_txt([1] * 24).replace(
        "     24\nDEMANDA BOMBEO", "     60\nDEMANDA BOMBEO", 1
    )
    with pytest.raises(ValueError, match="add up"):
        parse_programme_txt(text)


def test_programme_csv_sums_regions() -> None:
    header = "TIPO,RGE,VARIABLE," + ",".join(f"H{k:02d}" for k in range(1, 25))
    rows = [
        '"D","BAS","Demanda Neta",' + ",".join(["100"] * 24),
        '"D","CEN","Demanda Neta",' + ",".join(["50"] * 24),
        '"D","BAS","Perdidas",' + ",".join(["7"] * 24),
        '"G","BAS","Termica",' + ",".join(["999"] * 24),
    ]
    text = "﻿" + "\n".join([header, *rows])
    day = parse_programme_csv(text, dt.date(2024, 10, 29))
    assert day.hourly == (150.0,) * 24
    assert day.energy_mwh == 3600.0


def test_programme_target_date_from_file_name() -> None:
    assert programme_target_date("5D6F78_PD100106.zip") == dt.date(2010, 1, 6)
    with pytest.raises(ValueError):
        programme_target_date("SE421218.zip")
