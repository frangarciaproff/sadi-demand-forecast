"""Scores and tests of SPEC 4.5.

Errors are percentages of the definitive target: e = 100 (forecast / actual - 1).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy import stats


def pct_error(pred: pd.Series, actual: pd.Series) -> pd.Series:
    return 100 * (pred / actual - 1)


def scores(pred: pd.Series, actual: pd.Series) -> dict[str, float | int]:
    e = pct_error(pred, actual).dropna()
    abs_mwh = (pred - actual).abs().loc[e.index]
    return {
        "n_days": len(e),
        "mape_pct": round(float(e.abs().mean()), 3),
        "mae_gwh": round(float(abs_mwh.mean() / 1000), 3),
        "bias_pct": round(float(e.mean()), 3),
        "spread_sd_pct": round(float(e.std()), 3),
        "p90_abs_pct": round(float(e.abs().quantile(0.9)), 3),
        "max_abs_pct": round(float(e.abs().max()), 3),
    }


def nw_lag(n: int) -> int:
    """Newey-West automatic bandwidth floor(4 (n/100)^(2/9))."""
    return math.floor(4 * (n / 100) ** (2 / 9))


def long_run_variance(d: np.ndarray, lag: int) -> float:
    """Bartlett-kernel HAC variance of the mean-centred series (times n)."""
    x = d - d.mean()
    n = len(x)
    v = float(x @ x) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        v += 2 * w * float(x[k:] @ x[:-k]) / n
    return v


def diebold_mariano(
    loss_a: pd.Series, loss_b: pd.Series, h: int = 2, alternative: str = "greater"
) -> dict[str, float | int | str]:
    """DM test on d = loss_a - loss_b with HAC variance and the HLN correction.

    alternative "greater": H1 says model a has larger loss than b.
    "two-sided": H1 says the losses differ.
    """
    both = pd.concat([loss_a, loss_b], axis=1).dropna()
    d = (both.iloc[:, 0] - both.iloc[:, 1]).to_numpy(dtype=float)
    n = len(d)
    lag = nw_lag(n)
    var = long_run_variance(d, lag) / n
    dm = d.mean() / math.sqrt(var) if var > 0 else math.nan
    hln = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t = dm * hln
    if alternative == "greater":
        p = float(stats.t.sf(t, df=n - 1))
    else:
        p = float(2 * stats.t.sf(abs(t), df=n - 1))
    return {
        "n_days": n,
        "mean_loss_difference": round(float(d.mean()), 4),
        "statistic_hln": round(float(t), 3),
        "p_value": round(p, 4),
        "alternative": alternative,
        "hac_lag": lag,
    }


def block_bootstrap_ci(
    values: pd.DataFrame,
    stat: Callable[[np.ndarray], float],
    block: int = 7,
    reps: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """95 % CI of stat(resampled rows) with a moving-block bootstrap of the rows."""
    rng = np.random.default_rng(seed)
    arr = values.to_numpy(dtype=float)
    n = len(arr)
    starts_max = n - block + 1
    k = math.ceil(n / block)
    out = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, starts_max, size=k)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        out[r] = stat(arr[idx])
    lo, hi = np.percentile(out, [2.5, 97.5])
    return round(float(lo), 4), round(float(hi), 4)


def acf_ljung_box(e: pd.Series, lags: int = 14) -> dict[str, object]:
    """Autocorrelation of the errors (consecutive days) and the Ljung-Box test."""
    s = e.copy()
    s.index = pd.DatetimeIndex(s.index)
    s = s.asfreq("D")
    x = s - s.mean()
    n = int(s.notna().sum())
    denom = float((x**2).sum())
    rho = [float((x * x.shift(k)).sum() / denom) for k in range(1, lags + 1)]
    q = n * (n + 2) * sum(r**2 / (n - k) for k, r in enumerate(rho, start=1))
    return {
        "acf": [round(r, 3) for r in rho],
        "ljung_box_q": round(q, 2),
        "p_value": round(float(stats.chi2.sf(q, df=lags)), 4),
    }
