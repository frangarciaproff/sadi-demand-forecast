"""Supply balance check on the Síntesis Mensual bases (D7).

For every day of every base that still publishes the demand components (bases up to
2023-12), compare
    supply - exports            (generation by technology + imports - exports)
    local + losses + pumping    (demand by type)
day by day. This is the identity behind the target definition (SPEC 1).

Reads the base zips directly (no interim tables needed).
Writes results/eda/supply_balance.json.

Usage (from the repository root):
    uv run python scripts/check_supply_balance.py [--bases 2021-12 2022-12 2023-12]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from sadi_forecast.sintesis import build_sintesis, build_supply

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "cammesa"
TOLERANCE = 1e-5  # relative; rounding of MWh values with three decimals


def check_base(base: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "sintesis").mkdir()
        name = f"base_informe_mensual_{base}.zip"
        shutil.copy(RAW / "sintesis" / name, Path(tmp) / "sintesis" / name)
        by_type, _ = build_sintesis(Path(tmp))
        supply = build_supply(Path(tmp))
    needed = {"local_mwh", "losses_mwh", "pumping_mwh"}
    if by_type.empty or not needed <= set(by_type.columns):
        return {"base": base, "skipped": "demand components not published"}
    if by_type[list(needed)].isna().all().any():
        return {"base": base, "skipped": "demand components not published"}
    t = by_type.groupby("date")[sorted(needed)].sum()
    s = supply.groupby("date")[["supply_mwh", "export_mwh"]].sum()
    days = t.join(s, how="inner")
    lhs = days["supply_mwh"] - days["export_mwh"]
    rhs = days["local_mwh"] + days["losses_mwh"] + days["pumping_mwh"]
    rel = (lhs / rhs - 1).abs()
    return {
        "base": base,
        "first_day": str(days.index.min()),
        "last_day": str(days.index.max()),
        "days": len(days),
        "dates": [str(d) for d in days.index],
        "days_within_tolerance": int((rel <= TOLERANCE).sum()),
        "max_abs_relative_difference": float(rel.max()),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--bases", nargs="+", default=["2021-12", "2022-12", "2023-12"])
    args = p.parse_args(argv)
    results = [check_base(b) for b in args.bases]
    all_days: set[str] = set()
    for r in results:
        dates = r.pop("dates", [])
        assert isinstance(dates, list)
        if r.get("days") == r.get("days_within_tolerance"):
            all_days.update(dates)
    summary = {
        "tolerance_relative": TOLERANCE,
        "distinct_days_within_tolerance_in_fully_matching_bases": len(all_days),
        "first_day": min(all_days) if all_days else None,
        "last_day": max(all_days) if all_days else None,
        "bases": results,
    }
    out = ROOT / "results" / "eda"
    out.mkdir(parents=True, exist_ok=True)
    (out / "supply_balance.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
