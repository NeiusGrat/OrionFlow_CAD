"""Metric coarse fasteners: what size a hole diameter can be.

CAD tools model a threaded hole at the nominal size (M4 = 4.0), at the tap
drill (3.3) or not at all, and STEP rarely carries the thread. So a hole is
read as a *set* of possible (size, kind) and a bolted pair is wrong only when
the two sets share no size: clearance M4 over tapped M3 cannot take one screw.

Tap drill: ISO 2306 / common shop practice for coarse threads.
Clearance: ISO 273 fine / medium / coarse series.
"""
from __future__ import annotations

#: size: (nominal, tap drill, clearance fine, medium, coarse), mm
METRIC: dict[str, tuple[float, float, float, float, float]] = {
    "M2":   (2.0, 1.6, 2.2, 2.4, 2.6),
    "M2.5": (2.5, 2.05, 2.7, 2.9, 3.1),
    "M3":   (3.0, 2.5, 3.2, 3.4, 3.6),
    "M4":   (4.0, 3.3, 4.3, 4.5, 4.8),
    "M5":   (5.0, 4.2, 5.3, 5.5, 5.8),
    "M6":   (6.0, 5.0, 6.4, 6.6, 7.0),
    "M8":   (8.0, 6.8, 8.4, 9.0, 10.0),
    "M10":  (10.0, 8.5, 10.5, 11.0, 12.0),
    "M12":  (12.0, 10.2, 13.0, 13.5, 14.5),
}
KINDS = ("nominal", "tap", "clearance", "clearance", "clearance")
TOL = 0.05
#: Holes bigger than this are bores (bearing seats, pilots), not fastener holes.
MAX_FASTENER_HOLE = 14.5


def classify(diameter: float, tol: float = TOL) -> set[tuple[str, str]]:
    """Every (size, kind) this diameter is, within tolerance."""
    out = set()
    for size, dims in METRIC.items():
        for kind, d in zip(KINDS, dims):
            if abs(diameter - d) <= tol:
                out.add((size, kind))
    return out


def sizes(diameter: float) -> set[str]:
    return {s for s, _ in classify(diameter)}


def describe(diameter: float) -> str:
    c = sorted(classify(diameter))
    if not c:
        return f"Ø{diameter:.2f} (no standard metric size)"
    return f"Ø{diameter:.2f} = " + " / ".join(f"{k} {s}" for s, k in c)


def compatible(d1: float, d2: float) -> bool | None:
    """True/False when both diameters are recognised sizes, None when either is not."""
    if abs(d1 - d2) <= TOL:
        return True
    s1, s2 = sizes(d1), sizes(d2)
    if not s1 or not s2:
        return None
    return bool(s1 & s2)


def is_fastener_hole(diameter: float) -> bool:
    return diameter <= MAX_FASTENER_HOLE
