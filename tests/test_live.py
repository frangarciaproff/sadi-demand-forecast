"""Daily energy from 5-min and hourly instantaneous points."""

from __future__ import annotations

import math

from sadi_forecast.live import STEP_H, daily_energy


def test_constant_power_gives_24h_energy() -> None:
    pts = [{"dem": 1000} for _ in range(289)]
    assert math.isclose(daily_energy(pts, "dem", STEP_H), 24_000.0)


def test_trapezoid_halves_the_boundaries() -> None:
    pts = [{"p": 0}] + [{"p": 10} for _ in range(23)] + [{"p": 0}]
    assert daily_energy(pts, "p", 1.0) == 230.0


def test_missing_point_gives_nan() -> None:
    pts = [{"dem": 1}] * 288 + [{"x": 1}]
    assert math.isnan(daily_energy(pts, "dem", STEP_H))
