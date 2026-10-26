"""Build data/interim tables from the archived CAMMESA documents (all versions kept).

Usage (from the repository root):
    uv run python scripts/build_tables.py [--d1 PATH]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sadi_forecast.tables import build_programme, build_weekly_area, load_daily_history

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "cammesa"
OUT = ROOT / "data" / "interim"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--d1", type=Path, help="D1 daily file (.xlsx or the downloaded .zip)"
    )
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    OUT.mkdir(parents=True, exist_ok=True)

    weekly = build_weekly_area(RAW)
    weekly.to_parquet(OUT / "d5_area_hourly.parquet", index=False)
    logging.info(
        "d5_area_hourly: %d rows, %d versions", len(weekly), weekly["doc_id"].nunique()
    )

    programme = build_programme(RAW)
    programme.to_parquet(OUT / "d6_programme_hourly.parquet", index=False)
    logging.info(
        "d6_programme_hourly: %d rows, %d versions",
        len(programme),
        programme["doc_id"].nunique(),
    )

    d1_path = args.d1 or next(ROOT.glob("*Energ*Potencia*.zip"), None)
    if d1_path is not None:
        daily = load_daily_history(Path(d1_path))
        daily.to_parquet(OUT / "d1_daily.parquet", index=False)
        logging.info("d1_daily: %d rows from %s", len(daily), Path(d1_path).name)
    else:
        logging.warning("D1 file not found; d1_daily.parquet not built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
