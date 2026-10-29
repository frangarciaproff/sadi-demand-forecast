"""Candidate weather points per CAMMESA demand area (method_notes W4, O3).

Coordinates are city centres (WGS84, decimal degrees). The grid cell actually used by
each source is stored with the downloaded data (check C5: coast and elevation).
"""

from __future__ import annotations

from typing import NamedTuple


class Point(NamedTuple):
    key: str
    area: str  # CAMMESA demand area code
    name: str
    lat: float
    lon: float


POINTS: tuple[Point, ...] = (
    Point("caba", "GBA", "Buenos Aires (CABA)", -34.61, -58.38),
    Point("la_plata", "BAS", "La Plata", -34.92, -57.95),
    Point("mar_del_plata", "BAS", "Mar del Plata", -38.00, -57.56),
    Point("bahia_blanca", "BAS", "Bahía Blanca", -38.72, -62.27),
    Point("rosario", "LIT", "Rosario", -32.95, -60.65),
    Point("santa_fe", "LIT", "Santa Fe", -31.63, -60.70),
    Point("cordoba", "CEN", "Córdoba", -31.42, -64.18),
    Point("mendoza", "CUY", "Mendoza", -32.89, -68.83),
    Point("san_juan", "CUY", "San Juan", -31.54, -68.54),
    Point("tucuman", "NOA", "San Miguel de Tucumán", -26.82, -65.22),
    Point("salta", "NOA", "Salta", -24.79, -65.41),
    Point("resistencia", "NEA", "Resistencia", -27.46, -58.98),
    Point("posadas", "NEA", "Posadas", -27.37, -55.90),
    Point("neuquen", "COM", "Neuquén", -38.95, -68.06),
    Point("comodoro", "PAT", "Comodoro Rivadavia", -45.86, -67.48),
)
