import datetime as dt

import numpy as np
import pandas as pd

from sadi_forecast.evaluation import (
    block_bootstrap_ci,
    diebold_mariano,
    nw_lag,
    scores,
)
from sadi_forecast.models import DD, HybridModel, TreeModel


def _x(n: int, seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    x = pd.DataFrame({f"d_{c}": rng.normal(0, 2, n) for c in DD})
    x["dow"] = rng.integers(0, 7, n)
    y = 0.02 * x["d_cdd22"] + 0.01 * x["d_hdd16"] + rng.normal(0, 0.005, n)
    return x, pd.Series(y)


def test_hybrid_linear_part_is_non_negative_and_extrapolates() -> None:
    x, y = _x(600)
    m = HybridModel().fit(x, y)
    assert (m.coef >= 0).all()
    far = x.iloc[[0]].copy()
    far["d_cdd22"] = 50.0  # far beyond training range
    tree = TreeModel().fit(x, y)
    assert m.predict(far)[0] > tree.predict(far)[0] + 0.3


def test_dm_detects_larger_loss() -> None:
    rng = np.random.default_rng(1)
    idx = pd.date_range("2024-01-01", periods=300)
    b = pd.Series(np.abs(rng.normal(0, 1, 300)), index=idx)
    a = b + 0.5
    assert float(diebold_mariano(a, b)["p_value"]) < 0.01
    assert float(diebold_mariano(b, a)["p_value"]) > 0.99
    assert nw_lag(365) == 5


def test_bootstrap_ci_covers_mean() -> None:
    rng = np.random.default_rng(2)
    v = pd.DataFrame({"e": rng.normal(3, 1, 365)})
    lo, hi = block_bootstrap_ci(v, lambda a: float(a[:, 0].mean()), reps=300)
    assert lo < v["e"].mean() < hi


def test_scores_percent_of_actual() -> None:
    idx = [dt.date(2024, 1, d) for d in (1, 2)]
    s = scores(
        pd.Series([110.0, 90.0], index=idx), pd.Series([100.0, 100.0], index=idx)
    )
    assert s["mape_pct"] == 10.0 and s["bias_pct"] == 0.0
