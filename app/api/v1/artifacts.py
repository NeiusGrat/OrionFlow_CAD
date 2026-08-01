"""Serving built files: STEP, STL and GLB, wherever they ended up.

One handler, mounted at two paths. ``/api/v1/artifacts/...`` is what new builds
advertise; ``/api/v1/ofl/download/...`` is what is already written into the
``designs`` table for every part a user has saved, and into the artifact links
of any session still open. Retiring OFL generation must not break those, so the
legacy path is kept as a permanent alias rather than a deprecation.

The lookup falls through to object storage on purpose: per-request directories
live on the container that built them, and on a scale-to-zero host that
container is usually gone by the time the user clicks download.
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.services.artifacts import (
    OUTPUT_BASE,
    is_safe_filename,
    is_safe_request_id,
    storage_key,
)

router = APIRouter(tags=["Artifacts"])
legacy_router = APIRouter(tags=["Artifacts"])

_MEDIA_TYPES = {
    ".step": "application/STEP",
    ".stp": "application/STEP",
    ".stl": "application/sla",
    ".glb": "model/gltf-binary",
    ".fcstd": "application/octet-stream",
}


async def _serve(request_id: str, filename: str):
    if not is_safe_request_id(request_id):
        raise HTTPException(400, "Invalid request ID")
    if not is_safe_filename(filename):
        raise HTTPException(400, "Invalid filename")

    filepath = os.path.join(OUTPUT_BASE, request_id, filename)

    if not os.path.exists(filepath):
        # Local dir is ephemeral; older artifacts only exist in object storage.
        from app.config import settings

        if settings.is_s3_configured:
            from app.services.storage import get_storage

            url = get_storage().url_for(storage_key(request_id, filename))
            if url:
                return RedirectResponse(url=url, status_code=307)
        raise HTTPException(404, "File not found")

    ext = os.path.splitext(filename)[1].lower()
    return FileResponse(
        filepath,
        media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
        filename=filename,
    )


@router.get("/{request_id}/{filename}")
async def download_artifact(request_id: str, filename: str):
    """Download a built STEP/STL/GLB file."""
    return await _serve(request_id, filename)


@legacy_router.get("/download/{request_id}/{filename}")
async def download_artifact_legacy(request_id: str, filename: str):
    """The URL shape saved designs already hold. Kept working indefinitely."""
    return await _serve(request_id, filename)
