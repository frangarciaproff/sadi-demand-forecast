"""Feature rows for one target day from the current tables (forecast time).

Same construction as the training table (features.build_features), restricted to the
days the row needs: the target day and the 28 days before it (lags and reference).
Only the GFS weather source is used (production model M-fc).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sadi_forecast.features import LAGS, build_features, valid_versions
from sadi_forecast.targets import definitive_daily

GFS_COLUMN = "temperature_2m_previous_day2"


def window(day: dt.date) -> list[dt.date]:
    return [day - dt.timedelta(days=k) for k in range(LAGS, -1, -1)]


def features_for(
    day: dt.date,
    postop: pd.DataFrame,
    supply: pd.DataFrame,
    b1: pd.DataFrame,
    gfs_daily: pd.DataFrame,
    weights: pd.Series,
) -> pd.DataFrame:
    """Feature table over window(day); the row of `day` is the forecast input."""
    return build_features(
        definitive_daily(postop, supply),
        valid_versions(postop, b1),
        b1,
        {"gfs": gfs_daily},
        weights,
        window(day),
    )
