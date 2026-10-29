import datetime as dt

import numpy as np
import pandas as pd

from sadi_forecast.hourly import (
    HOURS,
    definitive_hourly,
    reference_shapes,
    shares_from_model,
)


def test_definitive_hourly_uses_latest_complete_base() -> None:
    rows = []
    for base, value in (("2021-12", 1.0), ("2022-12", 2.0)):
        for h in HOURS:
            rows.append(
                {
                    "base": base,
                    "date": dt.date(2021, 1, 1),
                    "hour": h,
                    "supply_mwh": value + 0.5,
                    "export_mwh": 0.5,
                }
            )
    rows.append(
        {
            "base": "2023-12",
            "date": dt.date(2021, 1, 1),
            "hour": 1,
            "supply_mwh": 9.0,
            "export_mwh": 0.0,
        }
    )  # incomplete base: ignored
    out = definitive_hourly(pd.DataFrame(rows))
    assert list(out.columns) == HOURS
    assert out.loc[dt.date(2021, 1, 1)].eq(2.0).all()


def test_reference_shapes_use_versions_known_at_issue() -> None:
    day = dt.date(2025, 3, 31)
    recs: list[dict[object, object]] = []
    for k, pub_offset in ((7, 2), (14, 2), (21, 2), (28, 2)):
        d = day - dt.timedelta(days=k)
        share = np.full(24, 1 / 24)
        share[0] += 0.01 * k / 7
        share = share / share.sum()
        recs.append(
            {
                **{h: float(v) for h, v in zip(HOURS, share, strict=True)},
                "date": d,
                "published_art": dt.datetime.combine(d, dt.time(20))
                + dt.timedelta(days=pub_offset),
            }
        )
    # a version of D-7 published after the issue time must be ignored
    late: dict[object, object] = {
        **{h: 1 / 24 for h in HOURS},
        "date": day - dt.timedelta(days=7),
        "published_art": dt.datetime.combine(day, dt.time(0)),
    }
    shapes = pd.DataFrame([*recs, late])
    s0, used = reference_shapes(shapes, [day])
    assert len(used[day]) == 4
    row = s0.to_numpy(dtype=float)[0]
    assert abs(row.sum() - 1) < 1e-12
    assert row[0] > 1 / 24


def test_shares_from_model_renormalise() -> None:
    x = pd.DataFrame(
        {"date": [dt.date(2025, 1, 1)] * 24, "hour": HOURS, "s0": [1 / 24] * 24}
    )
    s = shares_from_model(x, np.linspace(-0.1, 0.1, 24))
    assert abs(s.sum(axis=1).iloc[0] - 1) < 1e-12
