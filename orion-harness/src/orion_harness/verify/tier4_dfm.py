"""T4 geometric DFM tier (§7.2): wall thickness, per-direction
accessibility, and setup count via exact set cover over the 6 principal
directions (2^6=64 subsets, enumerated exactly, per spec). No solver
needed -- pure build123d/OCCT geometry queries.

Scoped approximation, stated plainly rather than silently: wall thickness
samples each PLANAR face's centroid along its inward normal (one ray per
face) rather than rasterizing the whole face; accessibility is
normal-alignment only -- a face is "accessible from direction d" if its
outward normal is within `angle_tol_deg` of +d -- and does NOT ray-cast
for occlusion by other geometry between the tool and the face. Both are
real, useful DFM signals and both are weaker than a production tool.
OF-TR-002 does not specify an occlusion algorithm; full visibility
ray-casting was out of scope for this pass.
"""

from __future__ import annotations

import itertools
import math

from build123d import Axis, GeomType, Vector

from ..contracts import GateResult, Metric
from ..registry import register_verifier
from .context import VerifyContext

PRINCIPAL_DIRECTIONS: dict[str, Vector] = {
    "+X": Vector(1, 0, 0),
    "-X": Vector(-1, 0, 0),
    "+Y": Vector(0, 1, 0),
    "-Y": Vector(0, -1, 0),
    "+Z": Vector(0, 0, 1),
    "-Z": Vector(0, 0, -1),
}

UNREACHABLE_SETUPS = float(len(PRINCIPAL_DIRECTIONS) + 1)  # sentinel: no combination of the 6 covers it


def _wall_thickness_at_face(shape, face, max_depth: float) -> float | None:
    if face.geom_type != GeomType.PLANE:
        return None
    center = face.center()
    normal = face.normal_at(center)
    inward = Vector(-normal.X, -normal.Y, -normal.Z)
    hits = shape.find_intersection_points(Axis(center, inward))
    # hits[0] is (approximately) the starting face itself; the next hit
    # along the inward ray is the nearest opposing surface.
    if len(hits) < 2:
        return None
    dist = (hits[1][0] - center).length
    if dist <= 1e-9 or dist > max_depth:
        return None
    return dist


@register_verifier("tier4.wall_min", version="1.0.0")
def wall_min_metric(ctx: VerifyContext) -> Metric:
    bbox = ctx.shape.bounding_box()
    diag = (
        (bbox.max.X - bbox.min.X) ** 2
        + (bbox.max.Y - bbox.min.Y) ** 2
        + (bbox.max.Z - bbox.min.Z) ** 2
    ) ** 0.5
    thicknesses = [
        t
        for face in ctx.shape.faces()
        if (t := _wall_thickness_at_face(ctx.shape, face, max_depth=diag)) is not None
    ]
    value = min(thicknesses) if thicknesses else 0.0
    return Metric(name="wall_min_mm", value=value, unit="mm")


def _face_accessible_directions(face, angle_tol_deg: float = 30.0) -> set[str]:
    normal = face.normal_at(face.center())
    cos_tol = math.cos(math.radians(angle_tol_deg))
    accessible = set()
    for name, direction in PRINCIPAL_DIRECTIONS.items():
        dot = normal.X * direction.X + normal.Y * direction.Y + normal.Z * direction.Z
        if dot >= cos_tol:
            accessible.add(name)
    return accessible


def _bbox_contains(face, at: list[float], tolerance: float) -> bool:
    bb = face.bounding_box()
    return (
        bb.min.X - tolerance <= at[0] <= bb.max.X + tolerance
        and bb.min.Y - tolerance <= at[1] <= bb.max.Y + tolerance
        and bb.min.Z - tolerance <= at[2] <= bb.max.Z + tolerance
    )


def _bbox_volume(face) -> float:
    bb = face.bounding_box()
    return max(bb.max.X - bb.min.X, 1e-9) * max(bb.max.Y - bb.min.Y, 1e-9) * max(
        bb.max.Z - bb.min.Z, 1e-9
    )


def _nearest_face(shape, at: list[float], tolerance: float = 1.0):
    """Among faces whose bounding box contains `at` (within `tolerance`),
    return the one with the smallest bounding-box volume -- this prefers a
    small local feature (a pocket floor, a boss top) over a large
    container face (the plate's own top face) that happens to also contain
    the point. Falls back to nearest-bounding-box-center distance when
    nothing contains the point.

    Deliberately not used for through-holes: a hole's cylindrical wall
    face has a radial normal, not an axial one, so this tier's
    normal-alignment accessibility heuristic does not apply to it --
    tier1.hole_present is the dedicated check for hole existence."""

    target = Vector(*at)
    containing = [f for f in shape.faces() if _bbox_contains(f, at, tolerance)]
    if containing:
        best = min(containing, key=_bbox_volume)
        return best, (best.bounding_box().center() - target).length

    best_face, best_dist = None, None
    for face in shape.faces():
        dist = (face.bounding_box().center() - target).length
        if best_dist is None or dist < best_dist:
            best_dist, best_face = dist, face
    return best_face, best_dist


@register_verifier("tier4.accessibility", version="1.0.0")
def accessibility_gate(ctx: VerifyContext) -> GateResult:
    """params: {"at": [x, y, z], "tolerance": mm}. Names a face by nearest
    centroid (reusing tier1.hole_present's position-matching convention)
    and asserts it is accessible from at least one of the 6 principal
    directions."""

    at = ctx.params.get("at")
    if at is None:
        return GateResult(
            name="accessibility", passed=False, reason="accessibility:no params.at given"
        )
    tolerance = float(ctx.params.get("tolerance", 1.0))
    face, dist = _nearest_face(ctx.shape, at, tolerance)
    if face is None or dist > tolerance:
        return GateResult(
            name="accessibility",
            passed=False,
            reason=f"accessibility:no face within tolerance={tolerance} of at={at}",
        )

    dirs = _face_accessible_directions(face)
    if not dirs:
        return GateResult(
            name="accessibility",
            passed=False,
            reason="accessibility:no principal direction can reach this face",
            evidence={"at": at},
        )
    return GateResult(name="accessibility", passed=True, evidence={"accessible_from": sorted(dirs)})


def min_setups(required_dirs_per_target: list[set[str]]) -> int | float:
    """Exact set cover over the 6 principal directions (2^6=64 subsets,
    enumerated exactly, per §7.2). Returns UNREACHABLE_SETUPS if some
    target has no accessible direction at all -- no number of setups helps."""

    if not required_dirs_per_target:
        return 0
    if any(not dirs for dirs in required_dirs_per_target):
        return UNREACHABLE_SETUPS

    direction_names = list(PRINCIPAL_DIRECTIONS)
    for r in range(0, len(direction_names) + 1):
        for combo in itertools.combinations(direction_names, r):
            combo_set = set(combo)
            if all(combo_set & dirs for dirs in required_dirs_per_target):
                return r
    return UNREACHABLE_SETUPS  # unreachable in practice: r=6 covers everything non-empty


@register_verifier("tier4.setups", version="1.0.0")
def setups_metric(ctx: VerifyContext) -> Metric:
    """params: {"targets": [[x, y, z], ...], "tolerance": mm}. Each target
    names a face (by nearest centroid) that must be machined; the metric
    is the minimum number of setups (distinct principal directions) whose
    union of accessible faces covers every target."""

    targets = ctx.params.get("targets", [])
    tolerance = float(ctx.params.get("tolerance", 1.0))
    required_dirs_per_target = []
    for at in targets:
        face, dist = _nearest_face(ctx.shape, at, tolerance)
        dirs = _face_accessible_directions(face) if face and dist <= tolerance else set()
        required_dirs_per_target.append(dirs)

    return Metric(name="setups", value=float(min_setups(required_dirs_per_target)), unit="count")
