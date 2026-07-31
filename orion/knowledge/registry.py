"""One place that knows what has been ingested.

The function graph searches across families, so it needs a way to reach rows
without importing each loader and knowing each file name. This is that: a
lookup from family to rows, reading the versioned datasets on disk.

Deliberately thin. It does not validate — the gate already did that at ingest —
and it does not cache aggressively, because a catalogue regenerated mid-session
should be visible without restarting.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))

#: family -> catalogue file. A dataset declares its own family, so this is only
#: the map from name to location.
CATALOGUES = {
    "rolling_bearing": "skf_deep_groove.json",
    "o_ring_gland": "parker_oring_glands.json",
}

_CACHE: dict[str, list[dict]] = {}


def _load(path: str) -> dict:
    with open(os.path.join(_HERE, path), encoding="utf-8") as fh:
        return json.load(fh)


def rows_for_family(family: str) -> list[dict]:
    """Every ingested row for a family, or an empty list if absent."""
    if family in _CACHE:
        return _CACHE[family]
    filename = CATALOGUES.get(family)
    if not filename:
        return []
    try:
        data = _load(filename)
    except (OSError, ValueError):
        return []
    rows = data.get("rows")
    if rows is None:
        # The bearing catalogue keeps a legacy mapping alongside `rows` for
        # callers that have not migrated; accept either shape.
        legacy = data.get("bearings") or {}
        rows = [{"designation": k, **v} for k, v in legacy.items()]
    _CACHE[family] = rows
    return rows


def dataset_for_family(family: str) -> Optional[dict[str, Any]]:
    """The whole dataset, including its source and gate report."""
    filename = CATALOGUES.get(family)
    if not filename:
        return None
    try:
        return _load(filename)
    except (OSError, ValueError):
        return None


def families() -> list[str]:
    return sorted(f for f in CATALOGUES if rows_for_family(f))


def reset_cache() -> None:
    _CACHE.clear()
