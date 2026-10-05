"""Rolling bearings: designation -> bore x OD x width, from the SKF table.

The SKF deep-groove table in ``orion/knowledge`` (608 rows, every dimension
cross-checked against the catalogue's inch column) is the source. Miniature
6xx sizes and the 68xx/69xx shorthand are not printed under those names in
that catalogue, so they are added here from the ISO 15 dimension series.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_SKF = Path(__file__).resolve().parents[2] / "orion" / "knowledge" / "skf_deep_groove.json"

#: ISO 15 sizes missing from the SKF table under these names: (d, D, B) mm.
EXTRA: dict[str, tuple[float, float, float]] = {
    "623": (3, 10, 4), "624": (4, 13, 5), "625": (5, 16, 5), "626": (6, 19, 6),
    "627": (7, 22, 7), "629": (9, 26, 8), "688": (8, 16, 5), "689": (9, 17, 5),
    "MR63": (3, 6, 2.5), "MR74": (4, 7, 2.5), "MR85": (5, 8, 2.5), "MR105": (5, 10, 4),
    "MR115": (5, 11, 4), "MR128": (8, 12, 3.5),
    "6800": (10, 19, 5), "6801": (12, 21, 5), "6802": (15, 24, 5), "6803": (17, 26, 5),
    "6804": (20, 32, 7), "6805": (25, 37, 7), "6806": (30, 42, 7),
    "6900": (10, 22, 6), "6901": (12, 24, 6), "6902": (15, 28, 7), "6903": (17, 30, 7),
    "6904": (20, 37, 9), "6905": (25, 42, 9), "6906": (30, 47, 9),
}

_DESIGNATION = re.compile(
    r"(?<![A-Z0-9])(MR\d{2,3}|6\d{2,4}|16\d{3}|61[89]\d{2})"
    r"(?:[-\s]?(?:2?Z{1,2}|2?RS[H1]?|2?RSL|DDU|LLU|C3|N|NR|E|ETN9))*(?![0-9])",
    re.I)


@lru_cache(maxsize=1)
def table() -> dict[str, tuple[float, float, float]]:
    out: dict[str, tuple[float, float, float]] = {}
    try:
        data = json.loads(_SKF.read_text())
        for des, row in data.get("bearings", {}).items():
            out[des.upper()] = (float(row["d"]), float(row["D"]), float(row["B"]))
    except (OSError, ValueError, KeyError):
        pass
    for k, v in EXTRA.items():
        out.setdefault(k, tuple(float(x) for x in v))
    return out


def lookup(name: str) -> tuple[str, tuple[float, float, float]] | None:
    """'608ZZ', 'bearing_6202-2RS', 'Ball Bearing MR105ZZ' -> ('608', (8, 22, 7))."""
    t = table()
    for m in _DESIGNATION.finditer(name.upper().replace("_", " ")):
        des = m.group(1).upper()
        if des in t:
            return des, t[des]
    return None


def looks_like_bearing(name: str) -> bool:
    return "bearing" in name.lower() or lookup(name) is not None
