"""Project-wide constants fixed in SPEC.md (section 4.1)."""

from __future__ import annotations

import datetime as dt

# Last day usable for exploratory analysis; later data belongs to the test period.
EDA_CUTOFF = dt.date(2025, 9, 30)
TEST_START = dt.date(2025, 10, 1)
TEST_END = dt.date(2026, 9, 30)
N_AREAS = 9
