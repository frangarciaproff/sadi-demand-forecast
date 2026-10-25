"""Collector: archiving, failures, resume, documents, S3 sink, Lambda handler."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from types import ModuleType

import pytest

import collect_cammesa
import handler
from conftest import FakeCammesa, FakeS3, manifest


def test_snapshot_archives_raw_body_and_manifest(
    cc: ModuleType, sink: collect_cammesa.LocalSink
) -> None:
    assert cc.run_snapshot(sink, [1002, 1945])
    files = sorted(sink.raw_dir.glob("snapshot/*/*/*.json"))
    assert [f.parts[-3] for f in files] == ["1002", "1945"]
    rows = manifest(sink)
    assert [r["status"] for r in rows] == [200, 200]
    assert all(len(r["sha256"]) == 64 for r in rows)


def test_http_error_is_stored_as_error_file(
    cc: ModuleType, sink: collect_cammesa.LocalSink
) -> None:
    assert not cc.run_snapshot(sink, [999])
    assert list(sink.raw_dir.glob("snapshot/999/*/*.error.json"))


def test_backfill_resumes_and_retries_only_failures(
    cc: ModuleType, sink: collect_cammesa.LocalSink
) -> None:
    start, end = dt.date(2026, 1, 14), dt.date(2026, 1, 16)
    assert not cc.run_backfill(
        sink, [1002], start, end, force=False
    )  # 2026-01-15 fails (HTTP 500)
    FakeCammesa.requests = []
    cc.run_backfill(sink, [1002], start, end, force=False)
    assert len(FakeCammesa.requests) == 1
    assert "fecha=2026-01-15" in FakeCammesa.requests[0]


def test_docs_daily_nemo_uses_windows_under_five_days(
    cc: ModuleType, sink: collect_cammesa.LocalSink
) -> None:
    cc.run_docs(
        sink,
        "PROGRAMACION_DIARIA",
        dt.date(2019, 1, 1),
        dt.date(2019, 1, 12),
        force=False,
    )
    listings = [r for r in FakeCammesa.requests if "findDocumentosByNemoRango" in r]
    assert len(listings) == 3
    assert not list(sink.raw_dir.glob("docs_index/**/*.error.json"))


def test_docs_validation_and_url_encoding(
    cc: ModuleType, sink: collect_cammesa.LocalSink
) -> None:
    ok = cc.run_docs(
        sink,
        "PARTE_SEMANAL_UNIF",
        dt.date(2019, 1, 1),
        dt.date(2019, 1, 10),
        force=False,
    )
    assert not ok  # BAD.zip is not a zip
    day_dir = sink.raw_dir / "docs" / "PARTE_SEMANAL_UNIF" / "2019-01-02"
    names = sorted(p.name for p in day_dir.iterdir())
    assert "ID2019-01-01_PD.zip" in names
    assert "ID2019-01-01_alivio_09_AL_07.xls" in names
    assert any(
        n.startswith("ID2019-01-01_BAD.zip.") and n.endswith(".error") for n in names
    )


def test_docs_resume_skips_existing_and_reuses_old_listings(
    cc: ModuleType, sink: collect_cammesa.LocalSink
) -> None:
    span = (dt.date(2019, 1, 1), dt.date(2019, 1, 10))
    cc.run_docs(sink, "PARTE_SEMANAL_UNIF", *span, force=False)
    FakeCammesa.requests = []
    cc.run_docs(sink, "PARTE_SEMANAL_UNIF", *span, force=False)
    assert not any("findDocumentosByNemoRango" in r for r in FakeCammesa.requests)
    assert [r for r in FakeCammesa.requests if "findAttachmentByNemoId" in r] == [
        r for r in FakeCammesa.requests if "BAD.zip" in r
    ]


def test_s3_sink_and_handler(cc: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeS3()
    monkeypatch.setattr(cc.S3Sink, "__init__", _s3_init(fake))
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    assert handler.handler({"mode": "snapshot"}, None) == {
        "ok": True,
        "mode": "snapshot",
        "regions": [1002, 1945],
    }
    assert any(k.startswith("raw/cammesa/snapshot/1002/") for k in fake.store)
    assert any(k.startswith("raw/cammesa/manifest/") for k in fake.store)
    with pytest.raises(RuntimeError):
        handler.handler({"mode": "snapshot", "regions": [999]}, None)


def test_s3_docs_do_not_redownload(
    cc: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeS3()
    monkeypatch.setattr(cc.S3Sink, "__init__", _s3_init(fake))
    sink = cc.S3Sink("test-bucket")
    span = (dt.date(2019, 1, 1), dt.date(2019, 1, 10))
    cc.run_docs(sink, "PARTE_SEMANAL_UNIF", *span, force=False)
    n_docs = sum("/docs/" in k for k in fake.store)
    cc.run_docs(sink, "PARTE_SEMANAL_UNIF", *span, force=False)
    # only the failed BAD.zip is retried
    assert sum("/docs/" in k for k in fake.store) == n_docs + 1


def _s3_init(fake: FakeS3) -> Callable[..., None]:
    def init(
        self: collect_cammesa.S3Sink, bucket: str, prefix: str = "raw/cammesa/"
    ) -> None:
        self.s3 = fake  # type: ignore[assignment]  # test double
        self.bucket = bucket
        self.prefix = prefix

    return init
