"""Demand weights of the weather points (O3, design A').

Rule (fixed before any model is fitted):
1. Province shares of local demand from the Síntesis province sheet (D7), training
   days only.
2. Each province is assigned to the weather point nearest to its main demand centre
   (great-circle distance). The demand centre is the largest city or load area, not
   necessarily the capital (e.g. Río Negro: Alto Valle; Chubut: Puerto Madryn).
3. Buenos Aires (province + CABA in D7) is split with the Parte Semanal area shares:
   area GBA -> point caba; area BAS (rest of the province) -> split equally between
   mar_del_plata and bahia_blanca.
Points that receive no province keep weight 0 (la_plata, inside area GBA).
"""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from sadi_forecast.points import POINTS

# Main demand centre per Síntesis province name (normalized), lat/lon.
DEMAND_CENTRES: dict[str, tuple[float, float]] = {
    "catamarca": (-28.47, -65.78),
    "chaco": (-27.45, -58.99),
    "chubut": (-42.77, -65.04),  # Puerto Madryn (aluminium smelter)
    "cordoba": (-31.42, -64.18),
    "corrientes": (-27.47, -58.83),
    "entre rios": (-31.73, -60.53),  # Paraná
    "formosa": (-26.18, -58.17),
    "jujuy": (-24.19, -65.30),
    "la pampa": (-36.62, -64.29),  # Santa Rosa
    "la rioja": (-29.41, -66.86),
    "mendoza": (-32.89, -68.83),
    "misiones": (-27.37, -55.90),
    "neuquen": (-38.95, -68.06),
    "rio negro": (-38.95, -67.99),  # Alto Valle (Cipolletti - General Roca)
    "salta": (-24.79, -65.41),
    "san juan": (-31.54, -68.54),
    "san luis": (-33.30, -66.34),
    "santa cruz": (-46.44, -67.52),  # Caleta Olivia
    "santa fe": (-32.95, -60.65),  # Rosario
    "sgo.del estero": (-27.79, -64.26),
    "tucuman": (-26.82, -65.22),
}
BUENOS_AIRES = "buenos aires"
BAS_POINTS = ("mar_del_plata", "bahia_blanca")


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def nearest_point(centre: tuple[float, float]) -> str:
    return min(POINTS, key=lambda p: haversine_km(centre, (p.lat, p.lon))).key


def province_shares(provinces: pd.DataFrame, start: dt.date, end: dt.date) -> pd.Series:
    """Share of each province in local demand over [start, end] (latest base)."""
    p = provinces[(provinces["date"] >= start) & (provinces["date"] <= end)]
    p = p[p["province"] != "total"]
    latest = p.groupby("date")["base"].transform("max")
    totals = p[p["base"] == latest].groupby("province")["mwh"].sum()
    return totals / totals.sum()


def gba_share_of_buenos_aires(d5: pd.DataFrame, start: dt.date, end: dt.date) -> float:
    """GBA / (GBA + BAS) energy in the weekly area reports over [start, end]."""
    d = d5[(d5["date"] >= start) & (d5["date"] <= end) & ~d5["missing"]]
    d = d.sort_values(["date", "area", "pub_date"]).groupby(["date", "area"]).tail(1)
    d = d.set_index(["date", "area"])
    e = d["energy_mwh"].groupby(level="area").sum()
    return float(e["GBA"] / (e["GBA"] + e["BAS"]))


def point_weights(
    provinces: pd.DataFrame, d5: pd.DataFrame, start: dt.date, end: dt.date
) -> pd.DataFrame:
    """Weight per point (sums to 1) with the provinces assigned to it."""
    shares = province_shares(provinces, start, end)
    gba = gba_share_of_buenos_aires(d5, start, end)
    weights = {p.key: 0.0 for p in POINTS}
    members: dict[str, list[str]] = {p.key: [] for p in POINTS}
    for prov, share in shares.items():
        if prov == BUENOS_AIRES:
            weights["caba"] += share * gba
            members["caba"].append(f"{prov} (GBA {gba:.3f})")
            for key in BAS_POINTS:
                weights[key] += share * (1 - gba) / len(BAS_POINTS)
                members[key].append(f"{prov} (BAS)")
            continue
        if prov not in DEMAND_CENTRES:
            raise KeyError(f"no demand centre for province {prov!r}")
        key = nearest_point(DEMAND_CENTRES[prov])
        weights[key] += share
        members[key].append(str(prov))
    total = sum(weights.values())
    if abs(total - 1) > 1e-9:
        raise ValueError(f"point weights sum to {total}, not 1")
    out = pd.DataFrame(
        {
            "weight": pd.Series(weights),
            "provinces": pd.Series({k: ", ".join(v) for k, v in members.items()}),
        }
    )
    return out.sort_values("weight", ascending=False)
