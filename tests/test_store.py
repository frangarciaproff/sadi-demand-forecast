from pathlib import Path

import pandas as pd

from sadi_forecast.store import LocalStore, read_parquet, write_parquet


def test_local_store_round_trip(tmp_path: Path) -> None:
    s = LocalStore(tmp_path)
    s.write("forecasts/2026-10-30.json", b"{}")
    s.write("forecasts/sub/x.json", b"1")
    assert s.exists("forecasts/2026-10-30.json")
    assert not s.exists("forecasts/2026-10-31.json")
    assert s.list("forecasts/") == ["forecasts/2026-10-30.json", "forecasts/sub/x.json"]
    assert s.list("nothing/") == []
    df = pd.DataFrame({"a": [1.0, 2.0]})
    write_parquet(s, "state/t.parquet", df)
    pd.testing.assert_frame_equal(read_parquet(s, "state/t.parquet"), df)
