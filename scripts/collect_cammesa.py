"""Append-only archiver for CAMMESA demand data (SPEC.md, section 6).

Standard library only (boto3 is imported lazily, for the S3 sink on AWS Lambda).
Raw responses are stored unmodified and never overwritten.

Modes:
    snapshot  current-day endpoint (actual 5-min demand + CAMMESA hourly forecast)
    day       by-date endpoint for D-1 and D-7 (Argentina time)
    backfill  by-date endpoint for a date range (resumable, local only)
    regions   region list
    docs      CAMMESA published documents for a date range (resumable, local only):
              programacion = Programación Diaria, semanal = Parte Semanal,
              postoperativo = Parte Post Operativo (daily report and its
              complement, published ~1 month later)
    verify    check that every attachment in the archived listings exists on disk

Every run ends with a summary of failed downloads (also in logs/collector.log).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "cammesa"
LOG_DIR = ROOT / "logs"
BASE_URL = "https://api.cammesa.com/demanda-svc/demanda/"
PUB_URL = "https://api.cammesa.com/pub-svc/public/"
DOC_NEMOS = {
    "programacion": "PROGRAMACION_DIARIA",
    "semanal": "PARTE_SEMANAL_UNIF",
    "postoperativo": "PARTE_POST_OPERATIVO_UNIF",
}
# Listings of these nemos mix several publications (daily report and complement);
# attachments must be requested with the publication's own nemo.
USE_DOC_NEMO = {"PARTE_POST_OPERATIVO_UNIF"}
# Daily job look-back per nemo (complements appear ~1 month after the day).
RECENT_DAYS = {"PARTE_POST_OPERATIVO_UNIF": 45}
DOCS_TIMEOUT_S = 120
# Start of the document archive; older documents in listings are ignored by verify.
DOCS_ARCHIVE_START = dt.date(2010, 1, 1)
DOC_WINDOW_DAYS = {
    "PROGRAMACION_DIARIA": 4,
    "PARTE_SEMANAL_UNIF": 28,
    "PARTE_POST_OPERATIVO_UNIF": 4,
}  # API: daily nemos accept < 5 days
ART = dt.timezone(dt.timedelta(hours=-3))  # Argentina, no DST
DEFAULT_REGIONS = [1002, 1945]  # SADI total, Córdoba
TIMEOUT_S = 30
RETRIES = 3
BACKFILL_PAUSE_S = 1.0
USER_AGENT = "sadi-demand-forecast/0.1 (research archive; low-rate)"

log = logging.getLogger("collector")

# Failures of the current run, reported at the end (cleared per Lambda invocation).
FAILURES: list[str] = []


class Sink(Protocol):
    def save(self, key: str, body: bytes) -> str: ...
    def record(self, rec: dict) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalSink:
    """Files under data/raw/cammesa; manifest as one JSON line per fetch."""

    def __init__(self, raw_dir: Path = RAW_DIR) -> None:
        self.raw_dir = raw_dir

    def save(self, key: str, body: bytes) -> str:
        path = self.raw_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return (
            path.relative_to(ROOT).as_posix()
            if path.is_relative_to(ROOT)
            else str(path)
        )

    def exists(self, key: str) -> bool:
        return (self.raw_dir / key).exists()

    def record(self, rec: dict) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        with (self.raw_dir / "manifest.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class S3Sink:
    """Objects under s3://<bucket>/raw/cammesa/; one manifest object per fetch."""

    def __init__(self, bucket: str, prefix: str = "raw/cammesa/") -> None:
        import boto3  # available in the Lambda runtime

        self.s3 = boto3.client("s3")
        self.bucket = bucket
        self.prefix = prefix

    def save(self, key: str, body: bytes) -> str:
        full = self.prefix + key
        self.s3.put_object(
            Bucket=self.bucket, Key=full, Body=body, ContentType="application/json"
        )
        return f"s3://{self.bucket}/{full}"

    def exists(self, key: str) -> bool:
        resp = self.s3.list_objects_v2(
            Bucket=self.bucket, Prefix=self.prefix + key, MaxKeys=1
        )
        return any(o["Key"] == self.prefix + key for o in resp.get("Contents", []))

    def record(self, rec: dict) -> None:
        name = f"{rec['retrieved_utc']}_{rec['kind']}_{rec['region']}.json"
        key = f"{self.prefix}manifest/{rec['date']}/{name}"
        body = json.dumps(rec, ensure_ascii=False).encode("utf-8")
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json"
        )


def today_art() -> dt.date:
    return dt.datetime.now(ART).date()


def utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")


def fetch(url: str, timeout: float = TIMEOUT_S) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return exc.code, exc.read()
            last_exc = exc
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.HTTPException,  # e.g. IncompleteRead, RemoteDisconnected
        ) as exc:
            last_exc = exc
        wait = 2**attempt
        log.warning(
            "attempt %d failed for %s (%s); retry in %ds", attempt, url, last_exc, wait
        )
        time.sleep(wait)
    raise RuntimeError(f"failed after {RETRIES} attempts: {url}") from last_exc


def count_points(body: bytes) -> int | None:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    return len(data) if isinstance(data, list) else None


def fail(message: str) -> None:
    """Log a failure and keep it for the end-of-run summary."""
    FAILURES.append(message)
    log.error("%s", message)


def report_failures() -> int:
    """Log the end-of-run summary; returns the number of failures."""
    if FAILURES:
        log.error("RUN SUMMARY: %d failure(s)", len(FAILURES))
        for message in FAILURES:
            log.error("  - %s", message)
    else:
        log.info("RUN SUMMARY: no failures")
    return len(FAILURES)


def archive(sink: Sink, kind: str, region: str, day: dt.date | None, url: str) -> bool:
    """Fetch url and store the raw body. Returns True on success."""
    retrieved = utc_stamp()
    day_part = day.isoformat() if day else "na"
    base = {
        "retrieved_utc": retrieved,
        "kind": kind,
        "region": region,
        "date": day_part,
        "url": url,
    }
    try:
        status, body = fetch(url)
    except RuntimeError as exc:
        fail(f"{kind} {region} {day_part}: {exc}")
        sink.record({**base, "status": None, "error": str(exc)})
        return False

    n_points = count_points(body)
    ok = status == 200 and n_points is not None
    suffix = ".json" if ok else ".error.json"  # errors never count as archived
    location = sink.save(f"{kind}/{region}/{day_part}/{retrieved}{suffix}", body)
    sink.record(
        {
            **base,
            "status": status,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "n_points": n_points,
            "file": location,
        }
    )
    log.info(
        "%s region=%s date=%s status=%s points=%s",
        kind,
        region,
        day_part,
        status,
        n_points,
    )
    if not ok:
        fail(f"{kind} {region} {day_part}: HTTP {status}, points={n_points}")
    return ok


def by_date_url(region: int, day: dt.date) -> str:
    query = f"id_region={region}&fecha={day.isoformat()}"
    return f"{BASE_URL}ObtieneDemandaYTemperaturaRegionByFecha?{query}"


def run_snapshot(sink: Sink, regions: list[int]) -> bool:
    day = today_art()
    results = [
        archive(
            sink,
            "snapshot",
            str(r),
            day,
            f"{BASE_URL}ObtieneDemandaYTemperaturaRegion?id_region={r}",
        )
        for r in regions
    ]
    return all(results)


def run_day(sink: Sink, regions: list[int]) -> bool:
    today = today_art()
    days = [today - dt.timedelta(days=1), today - dt.timedelta(days=7)]
    results = [
        archive(sink, "by_date", str(r), d, by_date_url(r, d))
        for r in regions
        for d in days
    ]
    return all(results)


def has_valid_file(directory: Path) -> bool:
    return directory.is_dir() and any(
        not f.name.endswith(".error.json") for f in directory.glob("*.json")
    )


def run_backfill(
    sink: LocalSink, regions: list[int], start: dt.date, end: dt.date, force: bool
) -> bool:
    ok = True
    day = start
    while day <= end:
        for r in regions:
            target = sink.raw_dir / "by_date" / str(r) / day.isoformat()
            if not force and has_valid_file(target):
                continue
            ok &= archive(sink, "by_date", str(r), day, by_date_url(r, day))
            time.sleep(BACKFILL_PAUSE_S)
        day += dt.timedelta(days=1)
    return ok


def run_regions(sink: Sink) -> bool:
    return archive(sink, "regions", "all", today_art(), f"{BASE_URL}RegionesDemanda")


def windows(start: dt.date, end: dt.date, days: int) -> list[tuple[dt.date, dt.date]]:
    out, w0 = [], start
    while w0 <= end:
        out.append((w0, w0 + dt.timedelta(days=days)))
        w0 += dt.timedelta(days=days)
    return out


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def cached_listing(sink: LocalSink, nemo: str, w0: dt.date) -> bytes | None:
    folder = sink.raw_dir / "docs_index" / nemo / w0.isoformat()
    files = (
        sorted(f for f in folder.glob("*.json") if not f.name.endswith(".error.json"))
        if folder.is_dir()
        else []
    )
    return files[-1].read_bytes() if files else None


def run_docs(sink: Sink, nemo: str, start: dt.date, end: dt.date, force: bool) -> bool:
    """Archive every attachment of publication `nemo` published in [start, end]."""
    ok = True
    # Older listings are reused on resume; later re-publications (e.g. complements)
    # can still appear within RECENT_DAYS.
    stable_before = today_art() - dt.timedelta(days=max(7, RECENT_DAYS.get(nemo, 0)))
    for w0, w1 in windows(start, end, DOC_WINDOW_DAYS[nemo]):
        body: bytes | None = None
        if isinstance(sink, LocalSink) and not force and w1 <= stable_before:
            body = cached_listing(sink, nemo, w0)
        if body is None:
            q = urllib.parse.urlencode(
                {
                    "fechadesde": f"{w0.isoformat()}T03:00:00.000Z",
                    "fechahasta": f"{w1.isoformat()}T03:00:00.000Z",
                    "nemo": nemo,
                }
            )
            list_url = f"{PUB_URL}findDocumentosByNemoRango?{q}"
            retrieved = utc_stamp()
            base = {
                "retrieved_utc": retrieved,
                "kind": "docs_index",
                "region": nemo,
                "date": w0.isoformat(),
                "url": list_url,
            }
            try:
                status, body = fetch(list_url, timeout=DOCS_TIMEOUT_S)
            except RuntimeError as exc:
                fail(f"docs_index {nemo} window {w0}: {exc}")
                sink.record({**base, "status": None, "error": str(exc)})
                ok = False
                continue
            n_docs = count_points(body)
            listed = status == 200 and n_docs is not None
            suffix = ".json" if listed else ".error.json"
            location = sink.save(
                f"docs_index/{nemo}/{w0.isoformat()}/{retrieved}{suffix}", body
            )
            sink.record(
                {
                    **base,
                    "status": status,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "n_points": n_docs,
                    "file": location,
                }
            )
            log.log(
                logging.INFO if listed else logging.ERROR,
                "docs_index %s %s status=%s docs=%s",
                nemo,
                w0,
                status,
                n_docs,
            )
            time.sleep(BACKFILL_PAUSE_S)
            if not listed:
                fail(f"docs_index {nemo} window {w0}: HTTP {status}, not a list")
                ok = False
                continue
        for doc in json.loads(body):
            day = dt.datetime.strptime(doc["fecha"], "%d/%m/%Y").date()
            if not start <= day <= end:
                continue
            for att in doc.get("adjuntos") or []:
                key_dir = f"docs/{nemo}/{day.isoformat()}"
                fname = f"{safe_name(doc['id'])}_{safe_name(att['nombre'])}"
                if not force and sink.exists(f"{key_dir}/{fname}"):
                    continue
                att_nemo = doc.get("nemo") if nemo in USE_DOC_NEMO else None
                q = urllib.parse.urlencode(
                    {
                        "attachmentId": att["id"],
                        "docId": doc["id"],
                        "nemo": att_nemo or nemo,
                    }
                )
                url = f"{PUB_URL}findAttachmentByNemoId?{q}"
                rec = {
                    "retrieved_utc": utc_stamp(),
                    "kind": "doc",
                    "region": nemo,
                    "date": day.isoformat(),
                    "url": url,
                    "doc_id": doc["id"],
                    "doc_version": doc.get("version"),
                    "doc_nemo": doc.get("nemo"),
                    "doc_hora": doc.get("hora"),
                    "attachment": att["nombre"],
                }
                try:
                    status, blob = fetch(url, timeout=DOCS_TIMEOUT_S)
                except RuntimeError as exc:
                    fail(f"doc {nemo} {day} {att['nombre']}: {exc}")
                    sink.record({**rec, "status": None, "error": str(exc)})
                    ok = False
                    continue
                is_zip = att["nombre"].lower().endswith(".zip")
                good = status == 200 and (
                    blob[:2] == b"PK" if is_zip else len(blob) > 100
                )
                name = fname if good else f"{fname}.{rec['retrieved_utc']}.error"
                location = sink.save(f"{key_dir}/{name}", blob)
                sink.record(
                    {
                        **rec,
                        "status": status,
                        "bytes": len(blob),
                        "sha256": hashlib.sha256(blob).hexdigest(),
                        "file": location,
                    }
                )
                log.log(
                    logging.INFO if good else logging.ERROR,
                    "doc %s %s %s status=%s bytes=%d",
                    nemo,
                    day,
                    att["nombre"],
                    status,
                    len(blob),
                )
                if not good:
                    fail(
                        f"doc {nemo} {day} {att['nombre']}: HTTP {status}, invalid body"
                    )
                ok &= good
                time.sleep(BACKFILL_PAUSE_S)
    return ok


def verify_docs(sink: LocalSink, since: dt.date = DOCS_ARCHIVE_START) -> list[str]:
    """Attachments dated >= `since` in archived listings but absent on disk."""
    missing: list[str] = []
    for nemo in DOC_NEMOS.values():
        seen: set[str] = set()
        for path in sorted((sink.raw_dir / "docs_index" / nemo).rglob("*.json")):
            if path.name.endswith(".error.json"):
                continue
            for doc in json.loads(path.read_bytes()):
                date = dt.datetime.strptime(doc["fecha"], "%d/%m/%Y").date()
                if date < since:
                    continue
                day = date.isoformat()
                for att in doc.get("adjuntos") or []:
                    name = f"{safe_name(doc['id'])}_{safe_name(att['nombre'])}"
                    key = f"docs/{nemo}/{day}/{name}"
                    if key not in seen and not sink.exists(key):
                        missing.append(key)
                    seen.add(key)
    return missing


def run_docs_recent(sink: Sink, days: int) -> bool:
    """All publications, last `days` days (daily job; catches late re-publications)."""
    today = today_art()
    results = [
        run_docs(
            sink,
            nemo,
            today - dt.timedelta(days=max(days, RECENT_DAYS.get(nemo, 0))),
            today,
            False,
        )
        for nemo in DOC_NEMOS.values()
    ]
    return all(results)


def run_mode(sink: Sink, mode: str, regions: list[int]) -> bool:
    """Entry point shared by the CLI and the Lambda handler (non-backfill modes)."""
    if mode == "snapshot":
        return run_snapshot(sink, regions)
    if mode == "day":
        return run_day(sink, regions)
    if mode == "regions":
        return run_regions(sink)
    raise ValueError(f"unsupported mode: {mode}")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "mode", choices=["snapshot", "day", "backfill", "regions", "docs", "verify"]
    )
    p.add_argument("--doc", choices=sorted(DOC_NEMOS), help="docs: which publication")
    p.add_argument("--regions", type=int, nargs="+", default=DEFAULT_REGIONS)
    p.add_argument(
        "--start", type=dt.date.fromisoformat, help="backfill/docs start (YYYY-MM-DD)"
    )
    p.add_argument(
        "--end",
        type=dt.date.fromisoformat,
        help="backfill/docs end (default: yesterday/today ART)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="backfill/docs: re-fetch items already archived",
    )
    return p.parse_args(argv)


def _run(args: argparse.Namespace, sink: LocalSink) -> int:
    if args.mode == "verify":
        missing = verify_docs(sink)
        for key in missing:
            fail(f"missing on disk: {key}")
        log.info("verify: %d attachment(s) missing", len(missing))
        return 1 if missing else 0
    if args.mode == "docs":
        if args.doc is None or args.start is None:
            log.error("docs requires --doc and --start")
            return 2
        end = args.end or today_art()
        ok = run_docs(sink, DOC_NEMOS[args.doc], args.start, end, args.force)
        return 0 if ok else 1
    if args.mode != "backfill":
        return 0 if run_mode(sink, args.mode, args.regions) else 1
    if args.start is None:
        log.error("backfill requires --start")
        return 2
    end = args.end or today_art() - dt.timedelta(days=1)
    return 0 if run_backfill(sink, args.regions, args.start, end, args.force) else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging()
    FAILURES.clear()
    code = _run(args, LocalSink())
    report_failures()
    return code


if __name__ == "__main__":
    sys.exit(main())
