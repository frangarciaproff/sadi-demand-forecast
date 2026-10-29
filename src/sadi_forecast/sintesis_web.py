"""Where the Informe Síntesis Mensual bases are published (D7) and how to find them.

Each yearly page /historico-sintesis-mensual-<year>/ links the base packages of that
year; a month's base appears about the 20th of the next month (SPEC 4.1).
"""

from __future__ import annotations

import re

SITE = "https://cammesaweb.cammesa.com/"

# base label -> download path (from the /historico-sintesis-mensual-YYYY/ pages,
# 2026-10-26). The "refresh" query parameter is not needed.
BASES: dict[str, str] = {
    "2021-12": "download/base_informe_mensual_2021-12/?wpdmdl=41598",
    "2022-12": "download/base-informe-mensual-2022-12/?wpdmdl=44146",
    "2023-12": "download/base_informe_mensual_2023-12/?wpdmdl=47482",
    "2024-12": "download/base_informe_mensual_2024-12/?wpdmdl=49554",
    "2025-12": "download/base_informe_mensual_2025-12/?wpdmdl=51545",
    "2026-09": "download/base_informe_mensual_2026-09/?wpdmdl=53541",
}


YEAR_PAGE = SITE + "historico-sintesis-mensual-{year}/"
LINK_RE = re.compile(
    r"(download/base[-_]informe[-_]mensual[-_](\d{4})-(\d{2})/?\?wpdmdl=\d+)", re.I
)


def find_bases(html: str) -> dict[str, str]:
    """base label (YYYY-MM) -> download path, from a yearly Síntesis page."""
    out: dict[str, str] = {}
    for path, year, month in LINK_RE.findall(html):
        out.setdefault(f"{year}-{month}", path)
    return out
