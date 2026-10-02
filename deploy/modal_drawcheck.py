"""drawcheck (incoming drawing checker) on Modal.

Deploy:   python -m modal deploy deploy/modal_drawcheck.py
Secrets:  Modal secret "drawcheck-secrets" holding
            GEMINI_API_KEY   vision reader for scanned / outlined pages
            DRAWCHECK_TOKEN  bearer token every /api call must carry
Storage:  Modal Volume "drawcheck-runs" at /data (runs, review decisions,
          vision cache). Runs older than DRAWCHECK_RETENTION_DAYS are purged.

Separate from the orionflow-api app on purpose: customer drawings are
confidential and get their own secret, storage and token.

The served URL is https://<workspace>--drawcheck-web.modal.run
"""

import subprocess

import modal


def _build_stamp() -> str:
    """Commit the image was built from, '-dirty' if drawcheck/ differs from it."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "drawcheck"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" if sha else "unknown"
    except Exception:  # noqa: BLE001 - a deploy from a tarball has no git
        return "unknown"


volume = modal.Volume.from_name("drawcheck-runs", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    # DejaVu has the GD&T glyphs the report summary page needs.
    .apt_install("fonts-dejavu-core")
    .pip_install("fastapi", "python-multipart", "pymupdf>=1.24", "openpyxl", "pyyaml", "httpx", "pydantic>=2")
    .env({
        "DRAWCHECK_DATA": "/data/runs",
        "DRAWCHECK_CACHE": "/data/vision-cache",
        "DRAWCHECK_RETENTION_DAYS": "30",
        "DRAWCHECK_BUILD": _build_stamp(),
    })
    # copy=True: code is part of the image, so a code change is a new image (no stale mounts).
    .add_local_dir("drawcheck", "/root/drawcheck", copy=True,
                   ignore=["**/__pycache__", "**/*.pyc", "tests/**"])
)

app = modal.App("drawcheck", image=image)


@app.function(
    secrets=[modal.Secret.from_name("drawcheck-secrets")],
    volumes={"/data": volume},
    min_containers=0,     # scale to zero
    max_containers=1,     # one writer: the volume is never edited from two containers
    scaledown_window=600,
    timeout=1800,         # a multi-page vision read can take minutes
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    import os
    import sys

    sys.path.insert(0, "/root")
    from drawcheck import api

    if not os.environ.get("DRAWCHECK_TOKEN"):
        raise RuntimeError("refusing to serve customer drawings without DRAWCHECK_TOKEN")
    api.TOKEN = os.environ["DRAWCHECK_TOKEN"]
    api.PERSIST = volume.commit

    @api.app.get("/api/version")
    def version() -> dict:
        return {"build": os.environ.get("DRAWCHECK_BUILD", "unknown")}

    return api.app
