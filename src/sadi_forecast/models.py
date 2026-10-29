"""Model families of SPEC 4.3 on the relative target y = ln E(D) - ln ref(D).

F-tree: gradient-boosted trees on y.
F-hyb: non-negative least squares of y on the Δ degree days (D minus the reference
days) plus a free intercept, then the same trees on the residual. The linear part
lets the forecast move beyond the temperature changes seen in training; the
non-negativity keeps it physically monotone (more heating or cooling need never
lowers demand).

Settings fixed in DECISIONS 2026-10-29 before any fit; no hyperparameter search.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

import numpy as np
import pandas as pd
from scipy.optimize import nnls
from sklearn.ensemble import HistGradientBoostingRegressor

from sadi_forecast.calendar_ar import day_kind
from sadi_forecast.features import CDD_BASES, HDD_BASES, REF_LAGS

KINDS = ["", "holiday", "bridge", "non_working", "eve"]
DD = [f"hdd{b}" for b in HDD_BASES] + [f"cdd{b}" for b in CDD_BASES]
REL_LAGS = (3, 4, 5, 6)
CATEGORICAL = ["day_kind", "prev_day_kind", "next_day_kind"]
TREE_PARAMS: dict[str, object] = {
    "loss": "absolute_error",
    "learning_rate": 0.05,
    "max_iter": 400,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 20,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": 0,
}


def ref_off_days(dates: list[dt.date], lags: pd.DataFrame) -> pd.Series:
    """Off days (Sunday, holiday, bridge) among the reference days actually used."""
    lo = min(dates) - dt.timedelta(days=max(REF_LAGS))
    span = (max(dates) - lo).days + 1
    kinds = day_kind(lo + dt.timedelta(days=k) for k in range(span))
    out = []
    for d in dates:
        n = 0
        for k in REF_LAGS:
            if pd.isna(lags.at[d, f"lag_{k}"]):
                continue
            r = d - dt.timedelta(days=k)
            n += int(r.weekday() == 6 or kinds[r] in ("holiday", "bridge"))
        out.append(n)
    return pd.Series(out, index=lags.index, name="ref_off_n")


def design(f: pd.DataFrame, day_src: str, ref_src: str) -> pd.DataFrame:
    """Feature matrix; day_src / ref_src: weather source of D and of the references."""
    x = pd.DataFrame(index=f.index)
    x["dow"] = f["dow"].astype(int)
    for c in CATEGORICAL:
        x[c] = pd.Categorical(f[c].fillna(""), categories=KINDS)
    x["off_day"] = f["off_day"].astype(int)
    x["doy_sin"] = f["doy_sin"]
    x["doy_cos"] = f["doy_cos"]
    x["t"] = f[f"t_{day_src}"]
    x["d_t"] = f[f"t_{day_src}"] - f[f"ref_t_{ref_src}"]
    for c in DD:
        x[f"d_{c}"] = f[f"{c}_{day_src}"] - f[f"ref_{c}_{ref_src}"]
    for k in REL_LAGS:
        x[f"rl_{k}"] = np.log(f[f"lag_{k}"] / f["ref_mwh"])
    x["ref_off_n"] = ref_off_days(list(f.index), f)
    return x


def relative_target(f: pd.DataFrame) -> pd.Series:
    return pd.Series(np.log(f["target_mwh"] / f["ref_mwh"]), index=f.index)


class Model(Protocol):
    def fit(self, x: pd.DataFrame, y: pd.Series) -> Model: ...
    def predict(self, x: pd.DataFrame) -> np.ndarray: ...


class TreeModel:
    """F-tree."""

    def __init__(self) -> None:
        self.trees = HistGradientBoostingRegressor(**TREE_PARAMS)

    def fit(self, x: pd.DataFrame, y: pd.Series) -> TreeModel:
        self.trees.fit(x, y)
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.trees.predict(x))


class HybridModel:
    """F-hyb: NNLS on Δ degree days + intercept, trees on the residual."""

    linear_cols: tuple[str, ...] = tuple(f"d_{c}" for c in DD)

    def __init__(self) -> None:
        self.trees = HistGradientBoostingRegressor(**TREE_PARAMS)
        self.coef = np.zeros(len(self.linear_cols))
        self.intercept = 0.0

    def _matrix(self, x: pd.DataFrame) -> np.ndarray:
        return x[list(self.linear_cols)].to_numpy(dtype=float)

    def linear(self, x: pd.DataFrame) -> np.ndarray:
        return self._matrix(x) @ self.coef + self.intercept

    def fit(self, x: pd.DataFrame, y: pd.Series) -> HybridModel:
        a = self._matrix(x)
        ones = np.ones((len(a), 1))
        sol, _ = nnls(np.hstack([a, ones, -ones]), y.to_numpy(dtype=float))
        self.coef = sol[: a.shape[1]]
        self.intercept = float(sol[-2] - sol[-1])
        self.trees.fit(x, y - self.linear(x))
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return self.linear(x) + np.asarray(self.trees.predict(x))


FAMILIES: dict[str, type[TreeModel] | type[HybridModel]] = {
    "tree": TreeModel,
    "hyb": HybridModel,
}
