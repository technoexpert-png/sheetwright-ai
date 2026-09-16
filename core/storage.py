"""Where uploaded files live.

Two backends behind one interface. Local disk is the default so `docker compose
up` needs no cloud credentials; S3-compatible object storage (Fly Tigris, AWS
S3, MinIO, R2) is the production path.

The interface is deliberately tiny — put, get, delete, exists. Anything richer
(signed URLs, multipart, lifecycle rules) belongs to the backend that supports
it, not to a lowest-common-denominator abstraction that pretends every store is
the same.

Keys are `{org_id}/{upload_id}/{filename}`. Putting the tenant first means a
whole tenant's objects share a prefix, so deleting an org — or auditing what it
stored — is one prefix operation rather than a scan.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Protocol

from config import settings

# Anything outside this set is replaced, so a hostile filename cannot escape
# its prefix or confuse a shell somewhere downstream.
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(name: str) -> str:
    """Reduce an arbitrary upload name to something safe to use as a key part.

    Path separators and traversal sequences are the real risk: a filename of
    `../../etc/passwd` must not be able to write outside its directory.
    """
    name = name.replace("\\", "/").split("/")[-1]      # drop any directory part
    name = _SAFE.sub("_", name).lstrip(".")            # no leading dots either
    return name[:180] or "upload"


def build_key(org_id: uuid.UUID, upload_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{upload_id}/{safe_filename(filename)}"


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete_prefix(self, prefix: str) -> int: ...


class LocalStorage:
    """Filesystem backend for development and tests."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings().storage_local_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        # Defence in depth: even with safe_filename, verify the resolved path
        # is still inside root before writing to it.
        if not p.is_relative_to(self.root):
            raise ValueError(f"key escapes storage root: {key!r}")
        return p

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp name then rename: a reader can never observe a
        # half-written file, because rename is atomic within a filesystem.
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete_prefix(self, prefix: str) -> int:
        """Remove everything under a prefix — used when reaping a trial org."""
        p = self._path(prefix)
        if not p.is_dir():
            return 0
        n = sum(1 for f in p.rglob("*") if f.is_file())
        shutil.rmtree(p, ignore_errors=True)
        return n


class S3Storage:
    """S3-compatible backend: AWS S3, Fly Tigris, Cloudflare R2, MinIO.

    boto3 is imported lazily and is an optional dependency, so the local
    development path carries no AWS SDK.
    """

    def __init__(self) -> None:
        cfg = settings()
        if not cfg.s3_bucket:
            raise RuntimeError("storage_backend='s3' requires s3_bucket to be set")
        try:
            import boto3  # noqa: PLC0415
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(
                "S3 storage needs boto3: pip install boto3"
            ) from exc
        # endpoint_url is what makes this work against Tigris/R2/MinIO as well
        # as AWS; left unset it defaults to AWS.
        self._client = boto3.client("s3", endpoint_url=cfg.s3_endpoint_url)
        self._bucket = cfg.s3_bucket

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError  # noqa: PLC0415
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete_prefix(self, prefix: str) -> int:
        paginator = self._client.get_paginator("list_objects_v2")
        n = 0
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})
                n += len(keys)
        return n


def get_storage() -> Storage:
    backend = settings().storage_backend
    if backend == "s3":
        return S3Storage()
    if backend == "local":
        return LocalStorage()
    raise RuntimeError(f"unknown storage_backend {backend!r}; expected 'local' or 's3'")
