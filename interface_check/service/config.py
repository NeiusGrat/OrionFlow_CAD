"""Service configuration, all from the environment so one image runs everywhere.

    IC_DATABASE_URL        sqlite:///data/interface_check/ic.sqlite  |  postgresql+psycopg://...
    IC_STORAGE             local | s3
    IC_STORAGE_ROOT        local storage directory (default data/interface_check/store)
    IC_S3_BUCKET / IC_S3_ENDPOINT / IC_S3_REGION / IC_S3_KEY / IC_S3_SECRET
                           any S3 API; Supabase Storage: endpoint https://<ref>.supabase.co/storage/v1/s3
    IC_DISPATCH            local | modal
    IC_MODAL_APP           deployed Modal app holding the cad_<tier> functions (default orionflow-cad)
    IC_GLOBAL_CONCURRENCY  jobs running at once across all users (default 4 local, 50 modal)
    IC_JWT_SECRET          the main API's HS256 secret: OrionFlow access tokens are accepted as-is
    IC_JWT_ALG             default HS256
    IC_DEV_TOKEN           local development only: this bearer token is user "dev"
    IC_DEFAULT_PLAN        plan when the token carries none (default free)
    IC_ADMIN_USERS         comma-separated user ids allowed to read /api/admin/metrics
    IC_RETENTION_DAYS      delete jobs and their files after this many days (default 30; 0 = keep)
    IC_SIGNED_URL_TTL      seconds a download/upload URL stays valid (default 600)
    IC_WORK_ROOT           where workers create per-job scratch directories (default system temp)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass
class Config:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "IC_DATABASE_URL", "sqlite:///data/interface_check/ic.sqlite"))
    storage: str = field(default_factory=lambda: os.environ.get("IC_STORAGE", "local"))
    storage_root: str = field(default_factory=lambda: os.environ.get("IC_STORAGE_ROOT", "data/interface_check/store"))
    s3_bucket: str = field(default_factory=lambda: os.environ.get("IC_S3_BUCKET", ""))
    s3_endpoint: str = field(default_factory=lambda: os.environ.get("IC_S3_ENDPOINT", ""))
    s3_region: str = field(default_factory=lambda: os.environ.get("IC_S3_REGION", "us-east-1"))
    s3_key: str = field(default_factory=lambda: os.environ.get("IC_S3_KEY", ""))
    s3_secret: str = field(default_factory=lambda: os.environ.get("IC_S3_SECRET", ""))
    dispatch: str = field(default_factory=lambda: os.environ.get("IC_DISPATCH", "local"))
    modal_app: str = field(default_factory=lambda: os.environ.get("IC_MODAL_APP", "orionflow-cad"))
    global_concurrency: int = field(default_factory=lambda: _int(
        "IC_GLOBAL_CONCURRENCY", 50 if os.environ.get("IC_DISPATCH") == "modal" else 2))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("IC_JWT_SECRET", ""))
    jwt_alg: str = field(default_factory=lambda: os.environ.get("IC_JWT_ALG", "HS256"))
    dev_token: str = field(default_factory=lambda: os.environ.get("IC_DEV_TOKEN", ""))
    default_plan: str = field(default_factory=lambda: os.environ.get("IC_DEFAULT_PLAN", "free"))
    admin_users: set = field(default_factory=lambda: {u for u in os.environ.get("IC_ADMIN_USERS", "").split(",") if u})
    retention_days: float = field(default_factory=lambda: float(os.environ.get("IC_RETENTION_DAYS", "30")))
    signed_url_ttl: int = field(default_factory=lambda: _int("IC_SIGNED_URL_TTL", 600))
    work_root: str = field(default_factory=lambda: os.environ.get("IC_WORK_ROOT", ""))

    def storage_spec(self) -> dict:
        """Picklable description, so an isolated worker child can open the same storage."""
        return {"kind": self.storage, "root": self.storage_root, "bucket": self.s3_bucket,
                "endpoint": self.s3_endpoint, "region": self.s3_region, "key": self.s3_key,
                "secret": self.s3_secret}
