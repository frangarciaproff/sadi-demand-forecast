"""Table builders on a synthetic archive (zips built in a temporary directory)."""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from pathlib import Path

from sadi_forecast.tables import HOUR_COLS, build_programme, build_weekly_area
from test_parsing import WEEK, _balance_txt


def _archive(
    raw: Path, nemo: str, pub: str, doc_id: str, name: str, members: dict[str, str]
) -> None:
    folder = raw / "docs" / nemo / pub
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / f"{doc_id}_{name}", "w") as z:
        for member, text in members.items():
            z.writestr(member, text.encode("latin1"))
    index = raw / "docs_index" / nemo / pub
    index.mkdir(parents=True, exist_ok=True)
    listing = [{"id": doc_id, "fecha": pub, "hora": "21:30", "version": "v"}]
    (index / "20260101T000000Z.json").write_text(json.dumps(listing))


def test_build_weekly_area_keeps_versions_and_missing_rows(tmp_path: Path) -> None:
    _archive(
        tmp_path,
        "PARTE_SEMANAL_UNIF",
        "2026-01-08",
        "ID1",
        "SE010104.zip",
        {"SE01area.dem": WEEK},
    )
    _archive(
        tmp_path,
        "PARTE_SEMANAL_UNIF",
        "2026-02-05",
        "ID2",
        "SE010104.zip",
        {"SE01area.dem": WEEK},
    )
    df = build_weekly_area(tmp_path)
    assert len(df) == 2 * 5
    assert set(df["doc_id"]) == {"ID1", "ID2"}
    assert set(df["pub_time"]) == {"21:30"}
    assert set(HOUR_COLS) <= set(df.columns)
    assert (
        int(df["missing"].sum()) == 2 * 2
    )  # overflow row and unmarked row, per version


def test_build_programme_reads_txt(tmp_path: Path) -> None:
    text = _balance_txt([15000] * 24)
    _archive(
        tmp_path,
        "PROGRAMACION_DIARIA",
        "2010-01-05",
        "ID9",
        "PD100106.zip",
        {"balance.txt": text},
    )
    df = build_programme(tmp_path)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["target_date"] == dt.date(2010, 1, 6)
    assert row["source"] == "txt"
    assert row["energy_mwh"] == 15000 * 24
