"""HTTP service entry point (kept at this path for ``uvicorn interface_check.api:app``).

The service lives in :mod:`interface_check.service`: a stateless API in front of
a job store, object storage and isolated, resource-limited workers.
"""
from .service.api import app

__all__ = ["app"]
