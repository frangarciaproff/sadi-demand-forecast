"""Target construction (SPEC 1, 2.2): supplied energy = supply - exports.

Definitive: D7 supply - D7 exports (the operator's consolidated balance). The D8
complement is checked against it (median difference 0.003 % on training days).
Provisional: D8 daily report supply - D6 programmed exports.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

# A complement must be within this relative distance of D7 supply to be used when
# several complements exist for one day (SPEC 2.2).
COMPLEMENT_TOLERANCE = 0.002


def d7_daily(supply: pd.DataFrame) -> pd.DataFrame:
    """Per date, from the latest base containing it: supply7_mwh, exports7_mwh.

    A day counts only with 24 hours of supply and of exports (missing export cells
    are not taken as zero).
    """
    days = (
        supply.groupby(["base", "date"])
        .agg(
            supply7_mwh=("supply_mwh", "sum"),
            exports7_mwh=("export_mwh", "sum"),
            supply_hours=("supply_mwh", "count"),
            export_hours=("export_mwh", "count"),
        )
        .reset_index()
    )
    days = days[(days["supply_hours"] == 24) & (days["export_hours"] == 24)]
    return (
        days.sort_values(["date", "base"])
        .groupby("date")
        .tail(1)
        .reset_index(drop=True)
    )


def definitive_daily(postop: pd.DataFrame, supply: pd.DataFrame) -> pd.DataFrame:
    """Definitive daily target per date, with the D8 complement for comparison.

    target_mwh = D7 supply - D7 exports (NaN until D7 covers the day). With several
    complements, the one closest to D7 supply is kept (closest to the latest daily
    report before D7 exists). flag marks complements more than COMPLEMENT_TOLERANCE
    away from D7 supply; it is a quality indicator and does not remove the target.
    """
    d7 = d7_daily(supply).set_index("date")
    comps = postop[postop["kind"] == "complement"]
    daily = postop[postop["kind"] == "daily"].sort_values("published")
    last_daily = daily.groupby("date").tail(1).set_index("date")["supply_mwh"]
    rows = []
    for date in sorted(set(comps["date"]) | set(d7.index)):
        ref7_raw = d7["supply7_mwh"].get(date)
        exports7 = d7["exports7_mwh"].get(date)
        values = comps.loc[comps["date"] == date, "supply_mwh"].tolist()
        has7 = ref7_raw is not None and pd.notna(ref7_raw)
        ref7 = float(ref7_raw) if has7 else float("nan")  # type: ignore[arg-type]
        ref = ref7 if has7 else last_daily.get(date)
        chosen = (
            min(values, key=lambda v: abs(v / ref - 1))
            if values and ref is not None
            else (values[-1] if values else float("nan"))
        )
        flag = ""
        if not values:
            flag = "no_complement"
        elif has7 and abs(chosen / ref7 - 1) > COMPLEMENT_TOLERANCE:
            flag = "complement_far_from_d7"
        elif not has7 and len(values) > 1:
            flag = "multiple_complements_provisional"
        rows.append(
            {
                "date": date,
                "supply_mwh": chosen,
                "supply7_mwh": ref7_raw,
                "exports7_mwh": exports7,
                "target_mwh": ref7 - float(exports7 or 0.0) if has7 else float("nan"),
                "n_complements": len(values),
                "flag": flag,
            }
        )
    return pd.DataFrame(rows)


def provisional_daily(postop: pd.DataFrame, b1: pd.DataFrame) -> pd.DataFrame:
    """Every daily report as a provisional value: supply - programmed exports.

    b1: output of daily.b1_daily (target_date, exports_mwh, b1_total_mwh).
    """
    cols = ["date", "doc_id", "published", "supply_mwh"]
    cols += [c for c in ("hours_present", "n_units", "date_mismatch") if c in postop]
    daily = postop[postop["kind"] == "daily"][cols]
    prog = b1.rename(columns={"target_date": "date"})[
        ["date", "exports_mwh", "b1_total_mwh"]
    ]
    out = daily.merge(prog, on="date", how="left")
    out["provisional_mwh"] = out["supply_mwh"] - out["exports_mwh"].fillna(0.0)
    return out


# The Síntesis base of month M appears around the 19th-20th of month M+1 (base
# 2026-09 dated 2026-10-19). Day 20 is used as a conservative publication day.
D7_PUBLICATION_DAY = 20


def definitive_available_until(on: dt.date) -> dt.date:
    """Last day whose definitive (D7) value is published on date `on`.

    Backtest refits train only on labels published by the refit date (SPEC 4.1).
    """
    first_of_month = on.replace(day=1)
    months_back = 1 if on.day >= D7_PUBLICATION_DAY else 2
    end = first_of_month
    for _ in range(months_back - 1):
        end = (end - dt.timedelta(days=1)).replace(day=1)
    return end - dt.timedelta(days=1)
