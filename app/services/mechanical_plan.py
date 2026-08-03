"""What can be said about a part's engineering before the kernel builds it.

Between a frozen Blueprint and FreeCAD there was nothing. ``resolve()``
substitutes expressions into a graph and hands it over, so any engineering
judgement the model did not happen to have is simply absent — and the first
thing that notices is either OCC, three seconds later, or nobody.

This module is that missing stage. It reads the **resolved** graph, where every
dimension is a concrete number and every sketch is a list of line segments and
circles with real coordinates, and applies rules that are arithmetic rather than
opinion.

Two rules of its own that keep it honest:

**Only geometry decides ``blocking``.** Two holes that overlap are not a matter
of taste — the profile is invalid and the kernel will either fail or produce
something nobody asked for. A hole closer to an edge than 1.5 diameters is a
manufacturing rule of thumb, and rules of thumb are ``warning``. Confusing the
two would either block correct parts or wave through impossible ones.

**A finding names the numbers.** "Check hole spacing" is noise an engineer
learns to skip. "hole at (12, 0) r3 and hole at (17, 0) r3 overlap by 1.0 mm" is
something they can act on, and it is what makes these usable as a repair
diagnosis rather than only as a warning label.

Advisory by design. Nothing here blocks a build: the established rule in this
codebase is that geometry a user can look at beats nothing, and a heuristic that
refuses a part can only lose ground the closed form would have won. Findings
travel to the approval panel, where a person decides, and into the repair
diagnosis, where a false positive costs nothing because the model also has the
real measurements in front of it.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)

#: Feature parameters that are lengths and must therefore be positive. Anything
#: not listed is left alone — an enum, a boolean or a count is not a dimension,
#: and guessing from the name is how a checker starts inventing failures.
_POSITIVE = (
    "Length",
    "Length2",
    "Radius",
    "Radius2",
    "Diameter",
    "Depth",
    "Thickness",
    "Size",
    "Angle",
)

#: Multiple of hole diameter to the nearest edge before the land is considered
#: thin. Sourced from ``design_rules.min_hole_edge_distance`` so the studio and
#: the copilot quote the same number rather than two similar ones.
_EDGE_FACTOR = 1.5


def _finding(
    rule: str,
    severity: str,
    message: str,
    feature: str = "",
    **values: Any,
) -> dict:
    return {
        "rule": rule,
        "severity": severity,
        "message": message,
        "feature": feature,
        "values": values,
    }


# --------------------------------------------------------------------------- #
# geometry helpers — plain arithmetic, no kernel
# --------------------------------------------------------------------------- #
def _circles(sketch: dict) -> list[tuple[float, float, float]]:
    """(cx, cy, r) for every non-construction circle in a sketch.

    ``radius`` is the key the profile builders emit; ``r`` is accepted too
    because the arc primitives use it and a future builder might. Anything that
    cannot be read raises rather than being skipped: a checker that silently
    drops the geometry it was meant to check reports a clean bill of health for
    a part it never looked at, which is worse than not running at all. This was
    not hypothetical — the first version read ``g["r"]``, found nothing, and
    passed every overlapping-hole case in the suite.
    """
    out = []
    for g in sketch.get("geometry") or []:
        if g.get("type") != "Circle" or g.get("construction"):
            continue
        radius = g.get("radius", g.get("r"))
        if radius is None:
            raise KeyError(
                f"circle in sketch {sketch.get('id')!r} has no radius: " f"{sorted(g)}"
            )
        out.append((float(g["cx"]), float(g["cy"]), float(radius)))
    return out


def _segments(sketch: dict) -> list[tuple[float, float, float, float]]:
    out = []
    for g in sketch.get("geometry") or []:
        if g.get("type") == "LineSegment" and not g.get("construction"):
            try:
                out.append(
                    (float(g["sx"]), float(g["sy"]), float(g["ex"]), float(g["ey"]))
                )
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _point_to_segment(px: float, py: float, seg) -> float:
    """Shortest distance from a point to a finite segment.

    Finite, not infinite: a hole near the *extension* of an edge is not near the
    edge, and treating the line as unbounded is how a checker reports a clash
    with material that is not there.
    """
    sx, sy, ex, ey = seg
    dx, dy = ex - sx, ey - sy
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length_sq))
    return math.hypot(px - (sx + t * dx), py - (sy + t * dy))


def _extent(sketch: dict) -> Optional[tuple[float, float]]:
    """(width, height) of the sketch's bounding box, or None if it has none."""
    xs: list[float] = []
    ys: list[float] = []
    for cx, cy, r in _circles(sketch):
        xs += [cx - r, cx + r]
        ys += [cy - r, cy + r]
    for sx, sy, ex, ey in _segments(sketch):
        xs += [sx, ex]
        ys += [sy, ey]
    if not xs or not ys:
        return None
    return max(xs) - min(xs), max(ys) - min(ys)


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def _check_dimensions(graph: dict) -> list[dict]:
    """Every length the model resolved must be greater than zero.

    A negative or zero Pad length is not a subtle failure — nothing gets built —
    but it survives the static check, because that only rejects *literals* and a
    perfectly good expression can evaluate to -3 for the variables chosen.
    """
    found = []
    for feature in graph.get("features") or []:
        for key, value in (feature.get("parameters") or {}).items():
            if key not in _POSITIVE or not isinstance(value, (int, float)):
                continue
            if value <= 0:
                found.append(
                    _finding(
                        "positive_dimension",
                        "blocking",
                        f"{feature.get('label') or feature.get('id')}: "
                        f"{key} resolves to {value:g} mm — nothing can be built "
                        "from a dimension that is not positive",
                        feature.get("id", ""),
                        parameter=key,
                        value=value,
                    )
                )
    return found


def _check_holes(graph: dict) -> list[dict]:
    """Holes that overlap each other, and holes too close to an edge.

    Circles that *cross* are a broken profile. Circles that *nest* are an
    annulus — a bore inside an outer boundary — and flagging those would report
    every washer in the corpus as a clash, so containment is excluded rather
    than merely tolerated.
    """
    found = []
    for sketch in graph.get("sketches") or []:
        sid = sketch.get("id", "")
        circles = _circles(sketch)
        segments = _segments(sketch)

        for i in range(len(circles)):
            for j in range(i + 1, len(circles)):
                cx1, cy1, r1 = circles[i]
                cx2, cy2, r2 = circles[j]
                gap = math.hypot(cx2 - cx1, cy2 - cy1)
                # Nested: one is inside the other. That is a bore, not a clash.
                if gap <= abs(r1 - r2):
                    continue
                web = gap - r1 - r2
                if web < 0:
                    found.append(
                        _finding(
                            "hole_overlap",
                            "blocking",
                            f"{sid}: holes at ({cx1:g}, {cy1:g}) r{r1:g} and "
                            f"({cx2:g}, {cy2:g}) r{r2:g} overlap by "
                            f"{abs(web):g} mm",
                            sid,
                            web_mm=round(web, 4),
                        )
                    )
                elif web < min(r1, r2):
                    found.append(
                        _finding(
                            "thin_web",
                            "warning",
                            f"{sid}: only {web:g} mm of material between the "
                            f"holes at ({cx1:g}, {cy1:g}) and ({cx2:g}, "
                            f"{cy2:g}) — thinner than the smaller hole's radius",
                            sid,
                            web_mm=round(web, 4),
                        )
                    )

        for cx, cy, r in circles:
            if not segments:
                continue
            nearest = min(_point_to_segment(cx, cy, s) for s in segments)
            land = nearest - r
            if land < 0:
                found.append(
                    _finding(
                        "hole_breaks_edge",
                        "blocking",
                        f"{sid}: the hole at ({cx:g}, {cy:g}) r{r:g} crosses the "
                        f"outline by {abs(land):g} mm",
                        sid,
                        land_mm=round(land, 4),
                    )
                )
            elif land < _EDGE_FACTOR * (2 * r) - r:
                # min_hole_edge_distance is centre-to-edge; land is edge-to-edge,
                # hence the radius subtracted from it.
                found.append(
                    _finding(
                        "thin_land",
                        "warning",
                        f"{sid}: the hole at ({cx:g}, {cy:g}) leaves {land:g} mm "
                        f"to the nearest edge — under {_EDGE_FACTOR:g}× diameter "
                        "the land tears when the hole is loaded",
                        sid,
                        land_mm=round(land, 4),
                        recommended_mm=round(_EDGE_FACTOR * 2 * r - r, 4),
                    )
                )
    return found


def _check_dressups(graph: dict) -> list[dict]:
    """A fillet or chamfer bigger than the feature it is applied to.

    OCC either fails outright or swallows the edge, and both read to a user as
    "the kernel broke" rather than as a dimension that was never going to work.
    The comparison is against the smallest sketch extent in the part, which is
    the loosest defensible bound: anything tighter would need to know which edge
    the dressup actually lands on, and that is the kernel's job.
    """
    found = []
    extents = [
        e for e in (_extent(s) for s in graph.get("sketches") or []) if e is not None
    ]
    if not extents:
        return found
    smallest = min(min(w, h) for w, h in extents)

    for feature in graph.get("features") or []:
        if feature.get("type") not in ("Fillet", "Chamfer"):
            continue
        params = feature.get("parameters") or {}
        size = params.get("Radius", params.get("Size"))
        if not isinstance(size, (int, float)) or size <= 0:
            continue
        if size >= smallest / 2:
            found.append(
                _finding(
                    "dressup_too_large",
                    "blocking",
                    f"{feature.get('label') or feature.get('id')}: "
                    f"{size:g} mm on a part whose smallest face is "
                    f"{smallest:g} mm — the dressup consumes the edge it is "
                    "applied to",
                    feature.get("id", ""),
                    size_mm=size,
                    smallest_extent_mm=round(smallest, 4),
                )
            )
    return found


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def review(graph: dict) -> dict:
    """Mechanical findings for a resolved graph. Never raises.

    ``graph`` is the output of ``Blueprint.resolve()`` — concrete numbers, real
    sketch coordinates. Returns ``{"findings": [...], "blocking": n,
    "warnings": n}``.

    Swallows its own errors on purpose. This stage is advisory, and a checker
    that can take down a build by failing to check it is strictly worse than one
    that says nothing.
    """
    findings: list[dict] = []
    try:
        findings += _check_dimensions(graph)
        findings += _check_holes(graph)
        findings += _check_dressups(graph)
    except Exception as exc:  # noqa: BLE001 — advisory must never cost a build
        logger.warning("mechanical_review_failed", error=repr(exc))
        return {"findings": [], "blocking": 0, "warnings": 0, "error": str(exc)[:200]}

    return {
        "findings": findings,
        "blocking": sum(1 for f in findings if f["severity"] == "blocking"),
        "warnings": sum(1 for f in findings if f["severity"] == "warning"),
    }


def review_blueprint(bp: Any) -> dict:
    """``review`` for a frozen Blueprint, resolving it first."""
    try:
        graph = bp.resolve()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mechanical_resolve_failed", error=repr(exc))
        return {"findings": [], "blocking": 0, "warnings": 0, "error": str(exc)[:200]}
    graph.pop("_analysis", None)
    return review(graph)


def as_diagnosis(report: dict) -> str:
    """The findings as a repair instruction, or "" when there is nothing to say.

    Phrased as the problem and its numbers rather than as an instruction to
    "fix the geometry": the model repairs a derivation it can see is wrong far
    more reliably than one it is merely told is wrong.
    """
    rows = [f for f in report.get("findings") or [] if f["severity"] == "blocking"]
    if not rows:
        return ""
    body = "\n".join(f"  {f['message']}" for f in rows)
    return (
        "The part's geometry is not buildable as dimensioned:\n"
        f"{body}\n"
        "Re-derive the dimensions involved. These are measured from your own "
        "resolved sketch coordinates, not estimated."
    )
