import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import get_sintesis
from sadi_forecast.models import DD, HybridModel
from sadi_forecast.production import ModelMeta, latest_version, load, save


def _meta(version: str) -> ModelMeta:
    return ModelMeta(
        version=version,
        family="hyb",
        window_years=5,
        weather="gfs",
        train_first="2021-10-01",
        train_last="2026-09-30",
        n_train=10,
        features=[f"d_{c}" for c in DD],
        tree_params={},
        sklearn="x",
        python="x",
    )


def test_save_load_and_no_model_from_the_future(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    x = pd.DataFrame({f"d_{c}": rng.normal(0, 1, 200) for c in DD})
    y = pd.Series(0.02 * x["d_cdd22"])
    model = HybridModel().fit(x, y)
    for v in ("2026-09-01", "2026-10-01"):
        save(model, _meta(v), tmp_path)
    assert latest_version(tmp_path, dt.date(2026, 9, 30)).name == "2026-09-01"
    assert latest_version(tmp_path, dt.date(2026, 10, 1)).name == "2026-10-01"
    with pytest.raises(FileNotFoundError):
        latest_version(tmp_path, dt.date(2026, 8, 31))
    loaded, meta = load(tmp_path / "2026-10-01")
    assert meta.family == "hyb"
    assert np.allclose(loaded.predict(x), model.predict(x))


def test_find_bases_in_year_page() -> None:
    html = (
        '<a href="https://cammesaweb.cammesa.com/download/base_informe_mensual_2026-09/'
        '?wpdmdl=53541&amp;refresh=abc">x</a>'
        '<a href="https://cammesaweb.cammesa.com/download/base-informe-mensual-2026-08/'
        '?wpdmdl=53400">y</a>'
        '<a href="/download/informe-mensual-2026-09/?wpdmdl=1">z</a>'
    )
    assert get_sintesis.find_bases(html) == {
        "2026-09": "download/base_informe_mensual_2026-09/?wpdmdl=53541",
        "2026-08": "download/base-informe-mensual-2026-08/?wpdmdl=53400",
    }
