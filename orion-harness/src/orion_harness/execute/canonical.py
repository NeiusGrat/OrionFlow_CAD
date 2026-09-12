"""F1 / F2: geometry identity that survives re-export.

F1 (measured): the same build123d part exported to STEP twice produced
different SHA-256 digests. The only differing bytes were the ISO timestamp
inside the `FILE_NAME(...)` entity. Never hash raw STEP bytes for identity
or caching (anti-pattern §15.8).

F2 (measured): `(volume, area, n_faces, n_edges, n_vertices, bbox)` rounded
to 6 decimals hashed identically across rebuilds. That tuple is the
canonical `geom_hash` -- it is the one used for the cache key (R4) and the
rebuild-determinism gate; STEP canonicalization below is a secondary,
best-effort tool for comparing exported artifacts, not the source of truth.

Measured in this repo's environment (build123d 0.10.0, Windows) beyond what
OF-TR-002 §3 F1 reports for 0.11.1/Linux: a SECOND non-deterministic field,
`NEXT_ASSEMBLY_USAGE_OCCURRENCE('<n>', ...)`, where `<n>` is a plain
process-global counter in OCCT's STEP writer that increments on every
`export_step()` call regardless of content -- confirmed by exporting the
same shape three times in one process and seeing '1', '2', '3'. Like the
FILE_NAME timestamp, it must be stripped before hashing, or canonicalized
STEP identity silently breaks the moment two exports happen in the same
process (which is exactly what the rebuild-determinism check does).
"""

from __future__ import annotations

import hashlib
import json
import re

ROUND_DECIMALS = 6

# Matches the timestamp field inside STEP's FILE_NAME(...) header entity,
# e.g. FILE_NAME('part.step','2026-09-12T10:31:02',(...
_FILE_NAME_TIMESTAMP_RE = re.compile(
    r"(FILE_NAME\s*\(\s*'[^']*'\s*,\s*)'[^']*'",
)

# Matches OCCT's per-process monotonic counter embedded in this entity --
# not part of the geometry, but not a timestamp either (see module docstring).
_ASSEMBLY_COUNTER_RE = re.compile(
    r"(NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(\s*)'[^']*'",
)


def canonicalize_step_text(step_text: str) -> str:
    """Strip fields that vary across otherwise-identical exports (the
    FILE_NAME timestamp (F1) and OCCT's per-process assembly-usage
    counter) so canonicalized STEP text hashes identically."""

    text = _FILE_NAME_TIMESTAMP_RE.sub(r"\1'<canonicalized>'", step_text)
    text = _ASSEMBLY_COUNTER_RE.sub(r"\1'<canonicalized>'", text)
    return text


def hash_step_bytes(step_bytes: bytes) -> str:
    """Canonical-STEP hash: for determinism checks on exported files, not
    used for the geometry identity gate (use `geom_hash` for that)."""

    text = step_bytes.decode("utf-8", errors="replace")
    canonical = canonicalize_step_text(text)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def geometric_signature(shape) -> dict:
    """(volume, area, n_faces, n_edges, n_vertices, bbox) from a build123d
    Shape/Part/Compound, rounded to ROUND_DECIMALS."""

    bbox = shape.bounding_box()
    return {
        "volume": round(float(shape.volume), ROUND_DECIMALS),
        "area": round(float(shape.area), ROUND_DECIMALS),
        "n_faces": len(shape.faces()),
        "n_edges": len(shape.edges()),
        "n_vertices": len(shape.vertices()),
        "bbox": [
            round(float(bbox.min.X), ROUND_DECIMALS),
            round(float(bbox.min.Y), ROUND_DECIMALS),
            round(float(bbox.min.Z), ROUND_DECIMALS),
            round(float(bbox.max.X), ROUND_DECIMALS),
            round(float(bbox.max.Y), ROUND_DECIMALS),
            round(float(bbox.max.Z), ROUND_DECIMALS),
        ],
    }


def geom_hash(shape) -> str:
    """Canonical identity hash for a built shape (F2). This is the cache key
    component for the rebuild-determinism gate, never raw STEP bytes."""

    sig = geometric_signature(shape)
    canonical = json.dumps(sig, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
