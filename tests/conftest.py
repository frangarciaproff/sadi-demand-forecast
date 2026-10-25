"""Fixtures: a local fake of the CAMMESA endpoints and a collector bound to it."""

from __future__ import annotations

import datetime as dt
import http.server
import json
import threading
import urllib.parse
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import collect_cammesa


class FakeCammesa(http.server.BaseHTTPRequestHandler):
    """Mimics the rules observed on the real API (2026-10)."""

    requests: list[str] = []  # noqa: RUF012 - shared request log for assertions

    def do_GET(self) -> None:
        FakeCammesa.requests.append(self.path)
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        status, body = 200, b""
        if "ObtieneDemandaYTemperaturaRegionByFecha" in url.path:
            if q.get("fecha") == "2026-01-15":
                status = 500
            else:
                body = json.dumps(
                    [{"fecha": "x", "dem": i} for i in range(289)]
                ).encode()
        elif "ObtieneDemandaYTemperaturaRegion" in url.path:
            if q.get("id_region") == "999":
                status, body = 404, b"not found"
            else:
                body = json.dumps(
                    [{"fecha": "x", "demHoy": 1, "demPrevista": 2}]
                ).encode()
        elif "RegionesDemanda" in url.path:
            body = json.dumps([{"id": 1002}]).encode()
        elif "findDocumentosByNemoRango" in url.path:
            a = dt.date.fromisoformat(q["fechadesde"][:10])
            b = dt.date.fromisoformat(q["fechahasta"][:10])
            if q["nemo"] == "PROGRAMACION_DIARIA" and (b - a).days >= 5:
                body = (
                    b'{"status":"NOT_FOUND",'
                    b'"message":"El intervalo de fechas debe ser menor a 5 dias"}'
                )
            else:
                day = (a + dt.timedelta(days=1)).strftime("%d/%m/%Y")
                docs = [
                    {
                        "id": f"ID{a}",
                        "fecha": day,
                        "hora": "21:30",
                        "version": "v",
                        "adjuntos": [
                            {"id": "PD.zip", "nombre": "PD.zip"},
                            {
                                "id": "alivio 09 AL 07.xls",
                                "nombre": "alivio 09 AL 07.xls",
                            },
                            {"id": "BAD.zip", "nombre": "BAD.zip"},
                        ],
                    }
                ]
                body = json.dumps(docs).encode()
        elif "findAttachmentByNemoId" in url.path:
            assert " " not in self.path, "query must be URL-encoded"
            att = q["attachmentId"]
            if att == "BAD.zip":
                body = b"<html>error</html>"
            elif att.endswith(".xls"):
                body = b"\xd0\xcf\x11\xe0" + b"x" * 200
            else:
                body = b"PK\x03\x04" + b"z" * 200
        else:
            status = 404
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def fake_server() -> Iterator[str]:
    FakeCammesa.requests = []
    server = http.server.HTTPServer(("127.0.0.1", 0), FakeCammesa)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def cc(fake_server: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """collect_cammesa pointed at the fake server, with no pauses or retries."""
    monkeypatch.setattr(
        collect_cammesa, "BASE_URL", f"{fake_server}/demanda-svc/demanda/"
    )
    monkeypatch.setattr(collect_cammesa, "PUB_URL", f"{fake_server}/pub-svc/public/")
    monkeypatch.setattr(collect_cammesa, "BACKFILL_PAUSE_S", 0)
    monkeypatch.setattr(collect_cammesa, "RETRIES", 1)
    monkeypatch.setattr(collect_cammesa.time, "sleep", lambda _s: None)
    return collect_cammesa


@pytest.fixture
def sink(tmp_path: Path) -> collect_cammesa.LocalSink:
    return collect_cammesa.LocalSink(tmp_path / "raw")


class FakeS3:
    """In-memory stand-in for the boto3 S3 client methods used by S3Sink."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.store[Key] = Body

    def list_objects_v2(self, Bucket: str, Prefix: str, MaxKeys: int) -> dict[str, Any]:
        keys = sorted(k for k in self.store if k.startswith(Prefix))[:MaxKeys]
        return {"Contents": [{"Key": k} for k in keys]} if keys else {}


def manifest(sink: collect_cammesa.LocalSink) -> list[dict[str, Any]]:
    path = sink.raw_dir / "manifest.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
