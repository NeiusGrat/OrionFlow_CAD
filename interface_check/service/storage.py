"""Object storage for CAD binaries, reports and the part cache.

Layout (every job isolated, nothing shared and mutable):

    uploads/{user}/{upload_id}/{field}/{filename}     browser uploads land here (signed PUT)
    jobs/{job_id}/input/{field}/{filename}            moved here when the job is created
    jobs/{job_id}/output/{report.json|report.pdf|model.glb}
    cache/features/{hh}/{geometry_hash}.json.gz       part cache, written only by workers

Two backends with one interface: a local directory (development, tests) and
any S3 API — AWS, R2, or Supabase Storage through its S3 endpoint. Objects are
always private; the API hands out short-lived signed URLs, never public links.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator


class Storage:
    def put_file(self, key: str, path: str | Path) -> None: ...
    def get_file(self, key: str, path: str | Path) -> None: ...
    def put_bytes(self, key: str, data: bytes) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def head(self, key: str, n: int = 64) -> bytes: ...
    def size(self, key: str) -> int | None: ...
    def exists(self, key: str) -> bool: return self.size(key) is not None
    def copy(self, src: str, dst: str) -> None: ...
    def list(self, prefix: str) -> Iterator[str]: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def signed_get(self, key: str, ttl: int, filename: str | None = None) -> str | None: ...
    def signed_put(self, key: str, ttl: int, max_bytes: int) -> str | None: ...


def _safe(key: str) -> str:
    if key.startswith("/") or ".." in key.split("/") or "\\" in key:
        raise ValueError(f"unsafe storage key {key!r}")
    return key


class LocalStorage(Storage):
    """A directory. Signed URLs are not possible; the API serves these objects itself."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        return self.root / _safe(key)

    def put_file(self, key, path):
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        shutil.copyfile(path, tmp)
        os.replace(tmp, p)

    def get_file(self, key, path):
        shutil.copyfile(self._p(key), path)

    def put_bytes(self, key, data):
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def put_stream(self, key: str, chunks, max_bytes: int) -> int:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp, n = p.with_name(p.name + ".part"), 0
        with open(tmp, "wb") as fh:
            for chunk in chunks:
                n += len(chunk)
                if n > max_bytes:
                    fh.close()
                    tmp.unlink(missing_ok=True)
                    raise ValueError(f"upload exceeds {max_bytes // 2**20} MB")
                fh.write(chunk)
        os.replace(tmp, p)
        return n

    def get_bytes(self, key):
        return self._p(key).read_bytes()

    def head(self, key, n=64):
        with open(self._p(key), "rb") as fh:
            return fh.read(n)

    def size(self, key):
        p = self._p(key)
        return p.stat().st_size if p.is_file() else None

    def copy(self, src, dst):
        self.put_file(dst, self._p(src))

    def list(self, prefix):
        base = self._p(prefix)
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and not p.name.endswith(".part"):
                    yield p.relative_to(self.root).as_posix()

    def delete_prefix(self, prefix):
        base = self._p(prefix)
        n = sum(1 for _ in self.list(prefix))
        shutil.rmtree(base, ignore_errors=True)
        return n

    def signed_get(self, key, ttl, filename=None):
        return None

    def signed_put(self, key, ttl, max_bytes):
        return None

    def path(self, key: str) -> Path:
        return self._p(key)


class S3Storage(Storage):
    """Any S3 API. Supabase Storage: endpoint https://<project>.supabase.co/storage/v1/s3."""

    def __init__(self, bucket: str, endpoint: str = "", region: str = "us-east-1", key: str = "", secret: str = ""):
        import boto3
        from botocore.config import Config as BotoConfig

        self.bucket = bucket
        self.s3 = boto3.client(
            "s3", endpoint_url=endpoint or None, region_name=region,
            aws_access_key_id=key or None, aws_secret_access_key=secret or None,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"},
                              retries={"max_attempts": 5, "mode": "adaptive"}))

    def put_file(self, key, path):
        self.s3.upload_file(str(path), self.bucket, _safe(key))

    def get_file(self, key, path):
        self.s3.download_file(self.bucket, _safe(key), str(path))

    def put_bytes(self, key, data):
        self.s3.put_object(Bucket=self.bucket, Key=_safe(key), Body=data)

    def get_bytes(self, key):
        return self.s3.get_object(Bucket=self.bucket, Key=_safe(key))["Body"].read()

    def head(self, key, n=64):
        return self.s3.get_object(Bucket=self.bucket, Key=_safe(key), Range=f"bytes=0-{n - 1}")["Body"].read()

    def size(self, key):
        from botocore.exceptions import ClientError
        try:
            return int(self.s3.head_object(Bucket=self.bucket, Key=_safe(key))["ContentLength"])
        except ClientError:
            return None

    def copy(self, src, dst):
        self.s3.copy({"Bucket": self.bucket, "Key": _safe(src)}, self.bucket, _safe(dst))

    def list(self, prefix):
        pages = self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=_safe(prefix))
        for page in pages:
            for o in page.get("Contents", []):
                yield o["Key"]

    def delete_prefix(self, prefix):
        # One DeleteObject per key: batch DeleteObjects needs a Content-MD5 that
        # recent boto3 no longer sends, and S3-compatible stores (Supabase) refuse it.
        keys = list(self.list(prefix))
        for k in keys:
            self.s3.delete_object(Bucket=self.bucket, Key=k)
        return len(keys)

    def signed_get(self, key, ttl, filename=None):
        params = {"Bucket": self.bucket, "Key": _safe(key)}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        return self.s3.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl)

    def signed_put(self, key, ttl, max_bytes):
        # A presigned PUT cannot cap the body size; the API re-checks the stored
        # size against the plan limit before any job is created from it.
        return self.s3.generate_presigned_url("put_object", Params={"Bucket": self.bucket, "Key": _safe(key)},
                                              ExpiresIn=ttl)


def open_storage(spec: dict) -> Storage:
    if spec.get("kind") == "s3":
        return S3Storage(spec["bucket"], spec.get("endpoint", ""), spec.get("region", "us-east-1"),
                         spec.get("key", ""), spec.get("secret", ""))
    return LocalStorage(spec.get("root") or "data/interface_check/store")
