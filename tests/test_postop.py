"""Post Operativo table builder with the Node reader replaced by a fake."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from sadi_forecast import postop


def _archive(raw: Path, listed: str, doc_id: str, member: str, nemo: str) -> None:
    folder = raw / "docs" / postop.NEMO / listed
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / f"{doc_id}_{member}.zip", "w") as z:
        z.writestr(member, b"not a real database")
    index = raw / "docs_index" / postop.NEMO / listed
    index.mkdir(parents=True, exist_ok=True)
    listing = [{"id": doc_id, "nemo": nemo, "fecha": listed, "version": "v"}]
    (index / f"{doc_id}.json").write_text(json.dumps(listing))


def test_operating_day_comes_from_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    # A file of 2022-06-15 listed as the daily report of 2022-08-15.
    _archive(raw, "2022-08-15", "A1", "PO220615.mdb", postop.DAILY)
    _archive(raw, "2022-08-16", "B2", "PO220816.mdb", postop.COMPLEMENT)
    # FECHA of each database, in archive order (listing day 2022-08-15, then 08-16).
    fechas = iter(["2022-06-15", "2022-08-16"])

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        lines = [
            json.dumps(
                {
                    "path": path,
                    "fecha": next(fechas),
                    "hourly": [10.0] * 24,
                    "n_rows": 24,
                    "n_units": 1,
                    "hours_present": 24,
                    "bad_rows": 0,
                }
            )
            for path in cmd[2:]
        ]
        return subprocess.CompletedProcess(cmd, 0, "\n".join(lines), "")

    monkeypatch.setattr(postop, "_node", lambda: "node")
    monkeypatch.setattr(postop.subprocess, "run", fake_run)
    table = postop.build_postop(raw, tmp_path / "cache", workers=1)
    rows = table.set_index("doc_id")
    assert rows.loc["A1", "date"] == dt.date(2022, 6, 15)
    assert rows.loc["A1", "listed_date"] == dt.date(2022, 8, 15)
    assert bool(rows.loc["A1", "date_mismatch"])
    assert rows.loc["A1", "name_date"] == "2022-06-15"
    assert rows.loc["B2", "kind"] == "complement"
    assert rows.loc["A1", "supply_mwh"] == 240.0


def test_corrupt_zip_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    folder = raw / "docs" / postop.NEMO / "2023-05-08"
    folder.mkdir(parents=True)
    (folder / "C3_PO230508.zip").write_bytes(b"PK\x03\x04 truncated")
    monkeypatch.setattr(postop, "_node", lambda: "node")
    out = postop.parse_zips([folder / "C3_PO230508.zip"])
    assert "error" in out[folder / "C3_PO230508.zip"]
