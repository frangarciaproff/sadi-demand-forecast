"""Build data/interim tables from the archived CAMMESA documents (all versions kept).

Usage (from the repository root):
    uv run python scripts/build_tables.py [--d1 PATH] [--only d5 d6 d1 d7 d8 wx]
        [--workers N]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sadi_forecast.postop import build_postop
from sadi_forecast.sintesis import build_sintesis, build_supply
from sadi_forecast.tables import build_programme, build_weekly_area, load_daily_history
from sadi_forecast.weather import build_weather

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "cammesa"
RAW_WEATHER = ROOT / "data" / "raw" / "open_meteo"
WEATHER_TABLES = {"era5": "d4a_era5_hourly", "gfs_prev": "d4b_gfs_prev_hourly"}
OUT = ROOT / "data" / "interim"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--d1", type=Path, help="D1 daily file (.xlsx or the downloaded .zip)"
    )
    p.add_argument(
        "--only",
        nargs="+",
        choices=["d5", "d6", "d1", "d7", "d8", "wx"],
        default=["d5", "d6", "d1", "d7", "d8", "wx"],
        help="tables to build (default: all)",
    )
    p.add_argument(
        "--workers", type=int, default=4, help="parallel processes for d8 (default 4)"
    )
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    OUT.mkdir(parents=True, exist_ok=True)

    if "d5" in args.only:
        weekly = build_weekly_area(RAW)
        weekly.to_parquet(OUT / "d5_area_hourly.parquet", index=False)
        logging.info(
            "d5_area_hourly: %d rows, %d versions",
            len(weekly),
            weekly["doc_id"].nunique(),
        )

    if "d6" in args.only:
        programme = build_programme(RAW)
        programme.to_parquet(OUT / "d6_programme_hourly.parquet", index=False)
        logging.info(
            "d6_programme_hourly: %d rows, %d versions",
            len(programme),
            programme["doc_id"].nunique(),
        )

    if "d7" in args.only:
        by_type, by_prov = build_sintesis(RAW)
        if by_type.empty:
            logging.warning("no Síntesis bases found; run scripts/get_sintesis.py")
        else:
            by_type.to_parquet(OUT / "d7_sintesis_type_hourly.parquet", index=False)
            logging.info(
                "d7_sintesis_type_hourly: %d rows, bases %s",
                len(by_type),
                sorted(by_type["base"].unique()),
            )
        if not by_prov.empty:
            by_prov.to_parquet(OUT / "d7_sintesis_province_hourly.parquet", index=False)
            logging.info("d7_sintesis_province_hourly: %d rows", len(by_prov))

    if "d7" in args.only:
        supply = build_supply(RAW)
        if not supply.empty:
            supply.to_parquet(OUT / "d7_supply_hourly.parquet", index=False)
            logging.info("d7_supply_hourly: %d rows", len(supply))

    if "d8" in args.only:
        postop = build_postop(RAW, OUT / "cache" / "postop", workers=args.workers)
        if postop.empty:
            logging.warning("no Post Operativo files; run the collector docs mode")
        else:
            postop.to_parquet(OUT / "d8_postop_versions.parquet", index=False)
            logging.info(
                "d8_postop_versions: %d documents, %d days, kinds %s",
                len(postop),
                postop["date"].nunique(),
                postop["kind"].value_counts().to_dict(),
            )

    if "wx" in args.only:
        for source, table in WEATHER_TABLES.items():
            wx = build_weather(RAW_WEATHER, source)
            if wx.empty:
                logging.warning("no %s files; run scripts/get_weather.py", source)
                continue
            wx.to_parquet(OUT / f"{table}.parquet", index=False)
            logging.info(
                "%s: %d rows, %d points", table, len(wx), wx["point"].nunique()
            )

    if "d1" in args.only:
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
