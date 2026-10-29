"""Download CAMMESA Informe Síntesis Mensual base packages (D7). Standard library only.

Each December base holds the four calendar years ending in that December:
hourly national demand by type (2021-12 base: 2018-2021) and, from the 2022-12 base,
hourly demand by province (2019 onward). Overlapping bases are all kept, so revisions
between publications can be measured.

Files go to data/raw/cammesa/sintesis/<base>.zip and are never overwritten.
A manifest line per download is appended to data/raw/cammesa/sintesis/manifest.jsonl.

Usage (from the repository root):
    py -3 scripts/get_sintesis.py            # all bases in BASES
    py -3 scripts/get_sintesis.py --list     # show the registry and what is on disk
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw" / "cammesa" / "sintesis"
SITE = "https://cammesaweb.cammesa.com/"
USER_AGENT = "sadi-demand-forecast/0.1 (research archive; low-rate)"
TIMEOUT_S = 300
RETRIES = 3
PAUSE_S = 2.0

# base label -> download path (from the /historico-sintesis-mensual-YYYY/ pages,
# 2026-10-26). The "refresh" query parameter is not needed.
BASES: dict[str, str] = {
    "2021-12": "download/base_informe_mensual_2021-12/?wpdmdl=41598",
    "2022-12": "download/base-informe-mensual-2022-12/?wpdmdl=44146",
    "2023-12": "download/base_informe_mensual_2023-12/?wpdmdl=47482",
    "2024-12": "download/base_informe_mensual_2024-12/?wpdmdl=49554",
    "2025-12": "download/base_informe_mensual_2025-12/?wpdmdl=51545",
    "2026-09": "download/base_informe_mensual_2026-09/?wpdmdl=53541",
}


def _target(base: str) -> Path:
    return OUT_DIR / f"base_informe_mensual_{base}.zip"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                body: bytes = resp.read()
                return body
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            print(f"  attempt {attempt}/{RETRIES} failed: {exc}")
            time.sleep(5 * attempt)
    raise RuntimeError(f"download failed after {RETRIES} attempts: {last}")


def download(base: str) -> str:
    path = _target(base)
    if path.exists():
        return "exists"
    body = _fetch(SITE + BASES[base])
    tmp = path.with_suffix(".part")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(body)
    try:
        with zipfile.ZipFile(tmp) as z:
            members = z.namelist()
    except zipfile.BadZipFile:
        bad = path.with_suffix(".error.bin")
        tmp.replace(bad)
        raise RuntimeError(f"not a zip file (saved as {bad.name})") from None
    tmp.replace(path)
    rec = {
        "base": base,
        "url": SITE + BASES[base],
        "file": path.name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "members": len(members),
        "fetched_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    with (OUT_DIR / "manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return f"ok ({len(body) / 1e6:.1f} MB, {len(members)} members)"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--list", action="store_true", help="show registry and disk state")
    args = p.parse_args(argv)
    if args.list:
        for base in BASES:
            print(base, "on disk" if _target(base).exists() else "missing")
        return 0
    failures: list[str] = []
    for base in BASES:
        print(f"{base}: downloading...")
        try:
            print(f"{base}: {download(base)}")
        except RuntimeError as exc:
            failures.append(f"{base}: {exc}")
            print(f"{base}: FAILED {exc}")
        time.sleep(PAUSE_S)
    print(f"RUN SUMMARY: {len(failures)} failure(s)")
    for line in failures:
        print("  " + line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
