"""Download CAMMESA Informe Síntesis Mensual base packages (D7).

Each December base holds the four calendar years ending in that December:
hourly national demand by type (2021-12 base: 2018-2021) and, from the 2022-12 base,
hourly demand by province (2019 onward). Overlapping bases are all kept, so revisions
between publications can be measured.

Files go to data/raw/cammesa/sintesis/<base>.zip and are never overwritten.
A manifest line per download is appended to data/raw/cammesa/sintesis/manifest.jsonl.

New bases are found with --discover: the yearly pages
/historico-sintesis-mensual-<year>/ (this year and the previous one) are read and every
link to a "base informe mensual" package is added to data/raw/cammesa/sintesis/
registry.json, which extends BASES. A month's base is published about the 20th of the
next month (SPEC 4.1).

Usage (from the repository root):
    uv run python scripts/get_sintesis.py             # bases in BASES and the registry
    uv run python scripts/get_sintesis.py --discover  # find new bases, then download
    uv run python scripts/get_sintesis.py --list      # registry and what is on disk
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

from sadi_forecast.sintesis_web import BASES, SITE, YEAR_PAGE, find_bases

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw" / "cammesa" / "sintesis"
USER_AGENT = "sadi-demand-forecast/0.1 (research archive; low-rate)"
TIMEOUT_S = 300
RETRIES = 3
PAUSE_S = 2.0

REGISTRY = OUT_DIR / "registry.json"


def registry() -> dict[str, str]:
    found: dict[str, str] = {}
    if REGISTRY.exists():
        found = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {**found, **BASES}


def discover(years: list[int]) -> dict[str, str]:
    """Read the yearly pages and store new bases in the registry."""
    known = registry()
    new: dict[str, str] = {}
    for year in years:
        try:
            html = _fetch(YEAR_PAGE.format(year=year)).decode("utf-8", "replace")
        except RuntimeError as exc:
            print(f"{year}: page not read ({exc})")
            continue
        bases = find_bases(html)
        print(f"{year}: {len(bases)} base links")
        new.update({b: p for b, p in bases.items() if b not in known})
    if new:
        stored = (
            json.loads(REGISTRY.read_text(encoding="utf-8"))
            if REGISTRY.exists()
            else {}
        )
        stored.update(new)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(
            json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"new bases: {sorted(new) or 'none'}")
    return new


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
    url = SITE + registry()[base]
    body = _fetch(url)
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
        "url": url,
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
    p.add_argument("--discover", action="store_true", help="look for new bases first")
    args = p.parse_args(argv)
    if args.discover:
        this_year = dt.date.today().year
        discover([this_year - 1, this_year])
    bases = registry()
    if args.list:
        for base in sorted(bases):
            print(base, "on disk" if _target(base).exists() else "missing")
        return 0
    failures: list[str] = []
    for base in sorted(bases):
        if _target(base).exists():
            continue
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
