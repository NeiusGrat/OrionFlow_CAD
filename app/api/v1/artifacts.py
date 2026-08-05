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
    file_digest,
    is_safe_filename,
    is_safe_request_id,
    manifest_entry,
    read_manifest,
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
    ".json": "application/json",
}


def _integrity_error(directory: str, filename: str, verify: bool) -> str | None:
    """Why this file must not be served, or None to serve it.

    The size check is unconditional because it is a ``stat`` and it catches the
    cases that actually happen: a write or an upload that stopped early, and a
    directory rebuilt by a later build under a request id an old link still
    points at. A truncated GLB otherwise reaches the viewer as a part with
    missing faces, which reads as a modelling failure rather than as a broken
    download — the wrong bug entirely.

    The hash is opt-in. Verifying it on every request would mean re-reading the
    whole file on each viewer load to defend against corruption that leaves the
    length exactly intact, which is not the failure this system has.

    A build with no manifest is served unchecked: everything produced before the
    manifest existed has none, and those links have to keep working.
    """
    entry = manifest_entry(read_manifest(directory), filename)
    if not entry:
        return None

    path = os.path.join(directory, filename)
    expected_bytes = entry.get("bytes")
    if isinstance(expected_bytes, int):
        try:
            actual = os.path.getsize(path)
        except OSError:
            return None
        if actual != expected_bytes:
            return (
                f"{filename} is {actual} bytes; the build that produced it "
                f"recorded {expected_bytes}"
            )

    if verify and entry.get("sha256"):
        actual_digest = file_digest(path)
        if actual_digest and actual_digest["sha256"] != entry["sha256"]:
            return f"{filename} does not match the sha256 its build recorded"
    return None


async def _serve(request_id: str, filename: str, verify: bool = False):
    if not is_safe_request_id(request_id):
        raise HTTPException(400, "Invalid request ID")
    if not is_safe_filename(filename):
        raise HTTPException(400, "Invalid filename")

    directory = os.path.join(OUTPUT_BASE, request_id)
    filepath = os.path.join(directory, filename)

    if not os.path.exists(filepath):
        # Local dir is ephemeral; older artifacts only exist in object storage.
        from app.config import settings

        if settings.is_s3_configured:
            from app.services.storage import get_storage

            url = get_storage().url_for(storage_key(request_id, filename))
            if url:
                return RedirectResponse(url=url, status_code=307)
        raise HTTPException(404, "File not found")

    problem = _integrity_error(directory, filename, verify)
    if problem:
        # 409, not 500: the request was well formed and the server is healthy —
        # the stored artifact disagrees with the record of what was built, and
        # a caller can act on that by rebuilding.
        raise HTTPException(409, problem)

    ext = os.path.splitext(filename)[1].lower()
    return FileResponse(
        filepath,
        media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
        filename=filename,
    )


@router.get("/{request_id}/{filename}")
async def download_artifact(request_id: str, filename: str, verify: bool = False):
    """Download a built STEP/STL/GLB file.

    ``?verify=1`` additionally re-hashes the file against the digest its build
    recorded, for a caller that wants proof rather than a length check.
    """
    return await _serve(request_id, filename, verify)


@legacy_router.get("/download/{request_id}/{filename}")
async def download_artifact_legacy(
    request_id: str, filename: str, verify: bool = False
):
    """The URL shape saved designs already hold. Kept working indefinitely."""
    return await _serve(request_id, filename, verify)
