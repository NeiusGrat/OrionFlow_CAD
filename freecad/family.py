"""Derive a coarse part *family* from the part name.

The gNucleus dataset has no explicit family column; coverage must be evaluated
per family, so this maps the free-text name to a family label by keyword.
"""

from __future__ import annotations

# order matters: first hit wins
_FAMILY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("gear", ("gear", "pinion", "sprocket", "cog")),
    ("flange", ("flange",)),
    ("shaft", ("shaft", "axle")),
    ("washer", ("washer",)),
    ("ring", ("ring", "collar")),
    ("nut", ("nut",)),
    ("bushing", ("bushing", "bush")),
    ("spacer", ("spacer", "standoff")),
    ("frustum", ("frustum", "cone", "taper")),
    ("pin", ("pin",)),
    ("key", ("key", "keyway")),
    ("spline", ("spline",)),
    ("bracket", ("bracket", "mount")),
    ("plate", ("plate",)),
    ("pulley", ("pulley",)),
    ("step", ("step", "stair", "ladder")),
]


def classify_family(name: str) -> str:
    low = (name or "").lower()
    for fam, kws in _FAMILY_KEYWORDS:
        if any(k in low for k in kws):
            return fam
    return "other"
