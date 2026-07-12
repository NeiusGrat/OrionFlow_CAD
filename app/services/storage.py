"""
Storage backends for generated CAD artifacts.

Compilers always write to local disk first (the build123d exporters need a
real filesystem path). What happens next depends on the backend:

- LocalStorage: files stay in ``settings.output_dir`` and are served by the
  ``/outputs`` static mount. Fine for development; on hosts with ephemeral
  disks (Fly.io scale-to-zero) files disappear when the machine stops.
- S3Storage: additionally uploads each artifact to an S3-compatible bucket
  (AWS S3, Cloudflare R2, MinIO) and returns presigned download URLs, so
  artifacts survive restarts and can be fetched without hitting the API.

Selected automatically: S3 when ``settings.is_s3_configured``, else local.
"""

from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_CONTENT_TYPES = {
    ".step": "application/step",
    ".stp": "application/step",
    ".stl": "model/stl",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".json": "application/json",
}


class LocalStorage:
    """Serve artifacts from local disk via the /outputs static mount."""

    name = "local"

    def publish(self, local_path: Path, key: str | None = None) -> str:
        return f"outputs/{Path(local_path).name}"

    def url_for(self, filename: str) -> str | None:
        if (settings.output_dir / filename).exists():
            return f"outputs/{filename}"
        return None


class S3Storage:
    """Upload artifacts to an S3-compatible bucket, serve presigned URLs."""

    name = "s3"

    def __init__(self) -> None:
        import boto3  # optional dependency; only needed when S3 is configured
        from botocore.config import Config

        self._client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
            endpoint_url=settings.s3_endpoint_url or None,
            # Custom endpoints (Supabase/R2/MinIO) 403 presigned URLs unless
            # SigV4 is forced.
            config=Config(signature_version="s3v4"),
        )
        self._bucket = settings.s3_bucket

    def publish(self, local_path: Path, key: str | None = None) -> str:
        local_path = Path(local_path)
        key = key or local_path.name
        content_type = _CONTENT_TYPES.get(
            local_path.suffix.lower(), "application/octet-stream"
        )
        self._client.upload_file(
            str(local_path),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return self.url_for(key)

    def url_for(self, filename: str) -> str | None:
        try:
            self._client.head_object(Bucket=self._bucket, Key=filename)
        except Exception:
            return None
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": filename},
            ExpiresIn=settings.s3_presign_expiry_seconds,
        )


@lru_cache(maxsize=1)
def get_storage():
    if settings.is_s3_configured:
        try:
            storage = S3Storage()
            logger.info(f"Storage backend: s3 (bucket={settings.s3_bucket})")
            return storage
        except Exception as e:
            logger.error(f"S3 storage init failed, falling back to local: {e}")
    return LocalStorage()


def publish_artifacts(*paths) -> dict:
    """
    Upload artifacts to the active storage backend.

    Returns a mapping of file extension -> client-facing URL for every path
    that exists (e.g. {"glb": "...", "step": "...", "stl": "..."}). Upload
    failures are logged and skipped so a storage outage never fails a
    generation that already produced valid geometry locally.
    """
    storage = get_storage()
    urls: dict[str, str] = {}
    for p in paths:
        if not p:
            continue
        path = Path(p)
        if not path.exists():
            continue
        try:
            url = storage.publish(path)
            if url:
                urls[path.suffix.lstrip(".").lower()] = url
        except Exception as e:
            logger.warning(f"Artifact upload failed for {path.name}: {e}")
    return urls
