"""Key-value storage for the service: a local folder or an S3 bucket, same keys.

Keys follow the bucket layout (SPEC 7): raw/cammesa/..., raw/open_meteo/..., state/,
models/, forecasts/, scores/. LocalStore(root) maps a key to root/<key>, so on the PC
the archive under data/raw/ is read in place.
"""

from __future__ import annotations

import io
import mimetypes
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


class Store(Protocol):
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, body: bytes) -> None: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def write(self, key: str, body: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(body)
        tmp.replace(path)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        """Keys of the files under prefix (a folder prefix ending in /)."""
        base = self._path(prefix)
        if not base.is_dir():
            return []
        return sorted(
            str(p.relative_to(self.root)).replace("\\", "/")
            for p in base.rglob("*")
            if p.is_file() and not p.name.endswith(".part")
        )


class S3Store:
    def __init__(self, bucket: str, client: Any = None) -> None:
        if client is None:
            import boto3  # available in the Lambda runtime image

            client = boto3.client("s3")
        self.bucket = bucket
        self.s3 = client

    def read(self, key: str) -> bytes:
        body: bytes = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body

    def write(self, key: str, body: bytes) -> None:
        kind = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=kind)

    def exists(self, key: str) -> bool:
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=key, MaxKeys=1)
        return any(o["Key"] == key for o in resp.get("Contents", []))

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self.s3.list_objects_v2(**kwargs)
            keys += [o["Key"] for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return sorted(keys)
            token = resp["NextContinuationToken"]


def read_parquet(store: Store, key: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(store.read(key)))


def write_parquet(store: Store, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf)
    store.write(key, buf.getvalue())
