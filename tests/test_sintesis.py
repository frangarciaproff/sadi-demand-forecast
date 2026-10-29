"""Síntesis Mensual parsers on synthetic workbooks in the two observed layouts."""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from sadi_forecast.sintesis import (
    build_sintesis,
    daily_by_base,
    latest_daily,
    parse_province_sheet,
    parse_type_sheet,
    to_date,
)

META = ["AÑO", "MES", "N° MES", "N° DIA", "TIPO DIA", "DIA", "FECHA", "HORA"]
TYPE_2021 = [
    "Gran Usuario MEM",
    "DISTRIBUIDOR (demanda estacional+GUMEs)",
    "DEMANDA LOCAL [MWh]",
    "Exportacion",
    "Bombeo",
    "Perdidas",
    "DEMANDA TOTAL [MWh]",
]


def _xlsx(
    sheet: str,
    columns: list[str],
    days: list[dt.date],
    value: float,
    serial_dates: bool,
    hours: int = 24,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet
    ws.append(["DEMANDA TOTAL PASO HORARIO"])
    ws.append(["Unidad: MWh"])
    ws.append([])
    ws.append(META + columns)
    for d in days:
        cell: object = (d - dt.date(1899, 12, 30)).days if serial_dates else d
        for h in range(1, hours + 1):
            ws.append(
                [d.year, cell, d.month, d.day, "HABIL", "Lunes", cell, h]
                + [value] * len(columns)
            )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _base_zip(folder: Path, base: str, members: dict[str, bytes]) -> None:
    sint = folder / "sintesis"
    sint.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(sint / f"base_informe_mensual_{base}.zip", "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


D1, D2 = dt.date(2021, 12, 30), dt.date(2021, 12, 31)


def test_to_date_serial_and_datetime() -> None:
    assert to_date(43101) == dt.date(2018, 1, 1)
    assert to_date(dt.datetime(2018, 1, 1, 0, 0)) == dt.date(2018, 1, 1)
    assert to_date("x") is None


def test_parse_type_sheet_2021_layout() -> None:
    df = parse_type_sheet(_xlsx("DEMANDA", TYPE_2021, [D1], 10.0, serial_dates=True))
    assert len(df) == 24
    assert df["date"].unique().tolist() == [D1]
    assert df["local_mwh"].sum() == 240.0
    assert {"gu_mem_mwh", "losses_mwh", "total_mwh"} <= set(df.columns)


def test_parse_type_sheet_requires_local() -> None:
    with pytest.raises(ValueError, match="not found"):
        parse_type_sheet(_xlsx("X", ["Otra"], [D1], 1.0, serial_dates=False))


def test_parse_province_sheet_long_format() -> None:
    df = parse_province_sheet(
        _xlsx("Demanda por Provincia", ["BUENOS AIRES", "CÓRDOBA"], [D1], 5.0, False)
    )
    assert sorted(df["province"].unique()) == ["buenos aires", "cordoba"]
    assert len(df) == 48


def test_build_and_latest_daily(tmp_path: Path) -> None:
    _base_zip(
        tmp_path,
        "2021-12",
        {
            "Base de datos Horaria-Diaria 2021-12.xlsx": _xlsx(
                "DEMANDA", TYPE_2021, [D1, D2], 10.0, serial_dates=True
            )
        },
    )
    folder = "BASE_2022-12/Bases_Demanda_INFORME_MENSUAL/"
    _base_zip(
        tmp_path,
        "2022-12",
        {
            folder + "Demanda Horaria por Tipo.xlsx": _xlsx(
                "Demanda por Tipo", TYPE_2021, [D2], 11.0, serial_dates=True
            ),
            folder + "Demanda Horaria por Provincia.xlsx": _xlsx(
                "Demanda por Provincia", ["BUENOS AIRES"], [D2], 3.0, False
            ),
        },
    )
    by_type, by_prov = build_sintesis(tmp_path)
    assert sorted(by_type["base"].unique()) == ["2021-12", "2022-12"]
    assert by_prov["base"].unique().tolist() == ["2022-12"]
    latest = latest_daily(by_type).set_index("date")
    local = latest["local_mwh"].to_dict()
    assert local[D1] == 240.0  # only in 2021-12
    assert local[D2] == 264.0  # 2022-12 wins
    assert latest["base"].to_dict()[D2] == "2022-12"


def test_incomplete_day_is_nan() -> None:
    df = parse_type_sheet(
        _xlsx("DEMANDA", TYPE_2021, [D1], 1.0, serial_dates=True, hours=23)
    ).assign(base="2021-12")
    days = daily_by_base(df)
    assert days["n_hours"].iloc[0] == 23
    assert days["local_mwh"].isna().all()


def test_type_sheet_without_total_and_nested_copy(tmp_path: Path) -> None:
    folder = "BASE_2024-12/Bases_Demanda_INFORME_MENSUAL/"
    sheet = _xlsx("Demanda por Tipo", TYPE_2021[:3], [D2], 2.0, serial_dates=True)
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as z:
        z.writestr(folder + "Demanda Horaria por Tipo.xlsx", sheet)
    _base_zip(
        tmp_path,
        "2024-12",
        {
            folder + "Demanda Horaria por Tipo.xlsx": sheet,
            "BASE_2024-12/BASE_2024-12.zip": nested.getvalue(),
        },
    )
    by_type, _ = build_sintesis(tmp_path)
    assert len(by_type) == 24
    assert "total_mwh" not in by_type.columns
