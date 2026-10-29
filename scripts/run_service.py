"""Run the production service (SPEC 7) on a local folder or on the S3 bucket.

Local (the PC archive, state seeded with seed_state.py):
    uv run python scripts/run_service.py daily
    uv run python scripts/run_service.py monthly
    uv run python scripts/run_service.py score
S3 (needs boto3 and AWS credentials; the Lambda does the same):
    uv run --with boto3 python scripts/run_service.py daily --bucket <bucket>

--at YYYY-MM-DDTHH:MM runs as if it were that time in Argentina (checks only).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from sadi_forecast import service
from sadi_forecast.store import LocalStore, S3Store, Store

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["daily", "monthly", "score"])
    p.add_argument("--bucket")
    p.add_argument("--root", type=Path, default=ROOT / "data")
    p.add_argument("--at", type=dt.datetime.fromisoformat)
    args = p.parse_args(argv)
    store: Store = S3Store(args.bucket) if args.bucket else LocalStore(args.root)
    at = args.at or service.now_art()
    if args.mode == "daily":
        out = service.daily(store, at)
    elif args.mode == "monthly":
        out = service.monthly(store, at)
    else:
        out = {"scores_written": service.score(store)}
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
