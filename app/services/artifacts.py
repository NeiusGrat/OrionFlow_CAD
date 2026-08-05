"""Where a built part's files live, and the URL they are served at.

This used to belong to the OFL module, for the accidental reason that OFL was
the first thing to produce a file. It is not an OFL concern: the Blueprint path
— the one every studio user actually hits — writes its STEP, STL and GLB into
the same directory and hands out the same links. Leaving the definition inside
``ofl_sandbox`` meant that retiring OFL generation would have taken every
download link in production with it.

Two things here are deliberately immovable.

**The directory name.** ``data/ofl_outputs`` is where artifacts already are, on
every running host and in every ``request_id`` directory that has not been
swept. Renaming it to something tidier would orphan all of them for the sake of
a nicer string.

**The legacy URL.** ``/api/v1/ofl/download/<id>/<file>`` is not just a route —
it is *persisted*. ``designs.glb_path`` and its siblings hold whole URLs in that
shape for every design a user has ever saved, and ``storage_key_for`` parses
them back into object keys. So it stays served forever, whatever happens to the
rest of OFL; new builds simply advertise the neutral path instead.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

#: Root of the per-request artifact directories. See the docstring: the name is
#: historical and the files under it are real.
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "data", "ofl_outputs")

#: What new builds advertise.
URL_PREFIX = "/api/v1/artifacts"

#: What older saved designs hold in the database. Still served.
LEGACY_URL_PREFIX = "/api/v1/ofl/download"

#: Object-storage prefix. Unchanged from the OFL era on purpose — the objects
#: are already there under this prefix and re-keying them buys nothing.
STORAGE_PREFIX = "ofl"

#: The sidecar that says what a build produced. Written into the same
#: per-request directory as the artifacts and published alongside them, so the
#: record of what a file *should* be travels with the file rather than living
#: only in a database the download route does not consult.
MANIFEST_NAME = "manifest.json"

#: Bumped when the manifest's shape changes in a way a reader must notice.
MANIFEST_SCHEMA = "orionflow-artifact-v1"


def builder_stamp() -> str:
    """Which build of this service produced an artifact.

    The same string ``GET /health`` reports as ``build`` — a short commit sha,
    suffixed ``-dirty`` when the image was built from an uncommitted tree. It is
    set once per deploy in ``deploy/modal_app.py`` and read here rather than
    recomputed, because a container has no git tree to ask.

    This exists because a deploy has already once served stale code while
    reporting success. When that happens the geometry is wrong in a way nothing
    about the geometry itself reveals; the only evidence is which build wrote
    it, and that evidence has to be recorded at write time or not at all.
    """
    return os.environ.get("ORIONFLOW_BUILD", "unknown")


def file_digest(path: str, chunk: int = 1 << 20) -> Optional[dict[str, Any]]:
    """``{"name", "bytes", "sha256"}`` for one built file, or None if unreadable.

    Streamed rather than read whole: an FCStd with a dense mesh runs to tens of
    megabytes and this is called on the request path.

    Returns None instead of raising. A digest is evidence about an artifact, not
    the artifact — failing to compute one must never turn a successful build
    into a failed one.
    """
    h = hashlib.sha256()
    try:
        size = 0
        with open(path, "rb") as fh:
            while True:
                block = fh.read(chunk)
                if not block:
                    break
                size += len(block)
                h.update(block)
    except OSError:
        return None
    return {"name": os.path.basename(path), "bytes": size, "sha256": h.hexdigest()}


def write_manifest(workdir: str, manifest: dict[str, Any]) -> Optional[str]:
    """Write the sidecar into ``workdir``. Returns its path, or None on failure."""
    path = os.path.join(workdir, MANIFEST_NAME)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
    except OSError:
        return None
    return path


def read_manifest(directory: str) -> Optional[dict[str, Any]]:
    """The manifest for a build, or None when there is not a readable one.

    Takes a directory rather than a request id so the caller decides which
    ``OUTPUT_BASE`` it means — the download route resolves that itself and must
    not be second-guessed here.

    A missing manifest is not an error: every artifact built before this existed
    has none, and those downloads have to keep working.
    """
    try:
        with open(os.path.join(directory, MANIFEST_NAME), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def manifest_entry(manifest: Optional[dict], filename: str) -> Optional[dict]:
    """The recorded digest for one filename, matched by name across kinds."""
    if not manifest:
        return None
    files = manifest.get("files")
    if not isinstance(files, dict):
        return None
    for entry in files.values():
        if isinstance(entry, dict) and entry.get("name") == filename:
            return entry
    return None


def new_manifest(
    request_id: str,
    files: dict[str, Any],
    *,
    blueprint_hash: str = "",
    kernel: Optional[dict] = None,
    built_where: str = "",
) -> dict[str, Any]:
    """Assemble the record. Pure — writing it is a separate decision."""
    return {
        "schema": MANIFEST_SCHEMA,
        "request_id": request_id,
        "blueprint_hash": blueprint_hash,
        "builder": builder_stamp(),
        "kernel": kernel or {},
        "built_where": built_where,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def artifact_url(request_id: str, filename: str) -> str:
    """The client-facing link for one built file."""
    return f"{URL_PREFIX}/{request_id}/{os.path.basename(filename)}"


def storage_key(request_id: str, filename: str) -> str:
    """The object-storage key for one built file."""
    return f"{STORAGE_PREFIX}/{request_id}/{os.path.basename(filename)}"


def workdir(request_id: str) -> str:
    """The directory a build writes into. Created if absent."""
    path = os.path.join(OUTPUT_BASE, request_id)
    os.makedirs(path, exist_ok=True)
    return path


def is_safe_request_id(request_id: str) -> bool:
    """Request ids are 12 hex characters; anything else is not one of ours.

    Checked before the id reaches a path join — this and ``is_safe_filename``
    are the whole defence against a download route being walked out of the
    artifact tree.
    """
    return bool(request_id) and request_id.isalnum() and len(request_id) == 12


def is_safe_filename(filename: str) -> bool:
    return bool(filename) and not (
        ".." in filename or "/" in filename or "\\" in filename
    )
