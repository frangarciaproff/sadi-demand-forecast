"""Target construction (SPEC 1, 2.2): supplied energy = D8 supply - exports.

Definitive: D8 complement supply - D7 actual exports.
Provisional: D8 daily report supply - D6 programmed exports.
"""

from __future__ import annotations

import pandas as pd

# A complement must be within this relative distance of D7 supply to be used when
# several complements exist for one day (SPEC 2.2).
COMPLEMENT_TOLERANCE = 0.002


def d7_daily(supply: pd.DataFrame) -> pd.DataFrame:
    """Per date, from the latest base containing it: supply7_mwh, exports7_mwh."""
    days = (
        supply.groupby(["base", "date"])
        .agg(
            supply7_mwh=("supply_mwh", "sum"),
            exports7_mwh=("export_mwh", "sum"),
            hours=("hour", "nunique"),
        )
        .reset_index()
    )
    days = days[days["hours"] == 24]
    return days.sort_values(["date", "base"]).groupby("date").last().reset_index()


def definitive_daily(postop: pd.DataFrame, supply: pd.DataFrame) -> pd.DataFrame:
    """Definitive daily target per date with the complement choice and flags.

    Columns: date, supply_mwh (chosen complement), supply7_mwh, exports7_mwh,
    target_mwh, n_complements, flag ("" if clean).
    """
    d7 = d7_daily(supply).set_index("date")
    comps = postop[postop["kind"] == "complement"]
    daily = postop[postop["kind"] == "daily"].sort_values("published")
    last_daily = daily.groupby("date")["supply_mwh"].last()
    rows = []
    for date, g in comps.groupby("date"):
        ref7 = d7["supply7_mwh"].get(date)
        values = g["supply_mwh"].tolist()
        flag = ""
        if ref7 is not None and pd.notna(ref7):
            chosen = min(values, key=lambda v: abs(v / ref7 - 1))
            if abs(chosen / ref7 - 1) > COMPLEMENT_TOLERANCE:
                flag = "complement_far_from_d7"
        else:
            ref = last_daily.get(date)
            chosen = (
                min(values, key=lambda v: abs(v / ref - 1))
                if ref is not None
                else values[-1]
            )
            flag = "multiple_complements_provisional" if len(values) > 1 else ""
        exports7 = d7["exports7_mwh"].get(date)
        target = (
            chosen - exports7
            if exports7 is not None and pd.notna(exports7) and not flag
            else float("nan")
        )
        rows.append(
            {
                "date": date,
                "supply_mwh": chosen,
                "supply7_mwh": ref7,
                "exports7_mwh": exports7,
                "target_mwh": target,
                "n_complements": len(values),
                "flag": flag,
            }
        )
    return pd.DataFrame(rows)


def provisional_daily(postop: pd.DataFrame, b1: pd.DataFrame) -> pd.DataFrame:
    """Every daily report as a provisional value: supply - programmed exports.

    b1: output of daily.b1_daily (target_date, exports_mwh, b1_total_mwh).
    """
    daily = postop[postop["kind"] == "daily"][
        ["date", "doc_id", "published", "supply_mwh"]
    ]
    prog = b1.rename(columns={"target_date": "date"})[
        ["date", "exports_mwh", "b1_total_mwh"]
    ]
    out = daily.merge(prog, on="date", how="left")
    out["provisional_mwh"] = out["supply_mwh"] - out["exports_mwh"].fillna(0.0)
    return out
