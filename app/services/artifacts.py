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

import os

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
