"""Parte Post Operativo (D8): hourly supply from the Access database in each zip.

Supply = sum of VALORES_GENERADORES.ENERGIA over all units (imports are units of the
table). CONTROL_VALORES_CC repeats the combined-cycle units and is never added.
Databases are read in batches by tools/mdb/supply.mjs (Node, mdb-reader); results
are cached per document (JSON), so later runs only read new files.

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
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from sadi_forecast.tables import load_doc_index

log = logging.getLogger(__name__)

NEMO = "PARTE_POST_OPERATIVO_UNIF"
DAILY = "PARTE_POST_OPERATIVO"
COMPLEMENT = "PARTE_POST_OPERATIVO_COMP"
N_HOURS = 24
SUPPLY_COLS = [f"s{k:02d}" for k in range(1, N_HOURS + 1)]
CACHE_VERSION = 4  # 4: YACYHIPY excluded (tools/mdb/supply.mjs)
# Access databases are read with the Node package mdb-reader (tools/mdb): the Python
# readers tried (access-parser 0.0.6 and its 2025 master) fail on every row of the
# 2024 files.
TOOLS_DIR = Path(
    os.environ.get("SADI_MDB_TOOLS")
    or Path(__file__).resolve().parents[2] / "tools" / "mdb"
)
CHUNK = 25


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js not found (needed to read Access databases)")
    if not (TOOLS_DIR / "node_modules" / "mdb-reader").exists():
        raise RuntimeError(f"run: npm install --prefix {TOOLS_DIR}")
    return node


def parse_zips(paths: list[Path]) -> dict[Path, dict[str, object]]:
    """Hourly supply, operating day and row counts for a batch of archived zips."""
    node = _node()
    out: dict[Path, dict[str, object]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        mdb_of: dict[str, tuple[Path, str]] = {}
        for k, path in enumerate(paths):
            try:
                with zipfile.ZipFile(path) as z:
                    members = [n for n in z.namelist() if n.lower().endswith(".mdb")]
                    if not members:
                        raise ValueError("no .mdb in zip")
                    target = Path(tmp) / f"{k}.mdb"
                    target.write_bytes(z.read(members[0]))
                mdb_of[str(target)] = (path, members[0])
            except (zipfile.BadZipFile, ValueError, OSError) as exc:
                out[path] = {"error": f"{type(exc).__name__}: {exc}"}
        if mdb_of:
            proc = subprocess.run(
                [node, str(TOOLS_DIR / "supply.mjs"), *mdb_of],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in proc.stdout.splitlines():
                rec = json.loads(line)
                path, member = mdb_of[rec.pop("path")]
                rec["name_date"] = _name_date(member)
                out[path] = rec
    return out


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
    """(listed day, document id, path); folders are named by the listing day."""
    root = raw_dir / "docs" / NEMO
    if not root.exists():
        return
    for folder in sorted(root.iterdir()):
        if folder.is_dir():
            day = dt.date.fromisoformat(folder.name)
            for path in sorted(folder.glob("*.zip")):
                yield day, path.name.split("_", 1)[0], path


def _cache_file(path: Path, cache: Path) -> Path:
    return cache / f"{path.name}.json"


def _load_cached(path: Path, cache: Path) -> dict[str, object] | None:
    target = _cache_file(path, cache)
    if not target.exists():
        return None
    data: dict[str, object] = json.loads(target.read_text(encoding="utf-8"))
    return data if data.get("cache_version") == CACHE_VERSION else None


def _parse_and_cache(paths: list[Path], cache: Path) -> dict[Path, dict[str, object]]:
    results = parse_zips(paths)
    for path, res in results.items():
        if "error" not in res:
            res["cache_version"] = CACHE_VERSION
            _cache_file(path, cache).write_text(json.dumps(res), encoding="utf-8")
    return results


def build_postop(raw_dir: Path, cache_dir: Path, workers: int = 4) -> pd.DataFrame:
    """One row per archived document: operating day (from the database), listed
    day, kind (daily/complement), publication timestamp, hourly supply s01-s24 and
    supply_mwh."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    index = load_doc_index(raw_dir, NEMO)
    jobs = list(_iter_archive(raw_dir))
    results: dict[Path, dict[str, object]] = {}
    todo: list[Path] = []
    for _, _, path in jobs:
        cached = _load_cached(path, cache_dir)
        if cached is None:
            todo.append(path)
        else:
            results[path] = cached
    log.info("post operativo: %d cached, %d to parse", len(results), len(todo))
    chunks = [todo[i : i + CHUNK] for i in range(0, len(todo), CHUNK)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_parse_and_cache, c, cache_dir) for c in chunks]
        for i, fut in enumerate(as_completed(futures), 1):
            results.update(fut.result())
            if i % 20 == 0:
                log.info("post operativo: %d / %d chunks", i, len(chunks))
    records: list[dict[str, object]] = []
    for listed, doc_id, path in jobs:
        res = results.get(path)
        if res is None or "error" in res:
            log.warning(
                "post operativo skipped: %s (%s)",
                path.name,
                None if res is None else res["error"],
            )
            continue
        meta = index.get(doc_id, {})
        hourly = res["hourly"]
        assert isinstance(hourly, list)
        fecha, name_date = res.get("fecha"), res.get("name_date")
        day = dt.date.fromisoformat(str(fecha)) if fecha else listed
        rec: dict[str, object] = {
            "date": day,
            "doc_id": doc_id,
            "listed_date": listed,
            "name_date": name_date,
            "date_mismatch": day != listed,
            "kind": {DAILY: "daily", COMPLEMENT: "complement"}.get(
                meta.get("nemo", ""), "unknown"
            ),
            "published": meta.get("version", ""),
            "supply_mwh": float(sum(hourly)),
            "hours_present": res["hours_present"],
            "n_units": res["n_units"],
            "excluded_mwh": res.get("excluded_mwh", 0.0),
        }
        rec.update(dict(zip(SUPPLY_COLS, hourly, strict=True)))
        records.append(rec)
    return pd.DataFrame.from_records(records)
