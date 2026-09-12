"""T1 geometry tier (§7.2): compiles, single solid, watertight, deterministic
rebuild, named-feature presence, mass. ~10ms-1s. Runs only if T0 passed
(tier short-circuiting, §7.2); the dispatcher in runner/jobs.py decides
when a shape needs to be built into the VerifyContext before calling any
of these.
"""

from __future__ import annotations

from build123d import GeomType

from ..contracts import GateResult, Metric
from ..registry import register_verifier
from .context import VerifyContext


@register_verifier("tier1.single_solid", version="1.0.0")
def single_solid(ctx: VerifyContext) -> GateResult:
    n = len(ctx.shape.solids())
    if n != 1:
        return GateResult(
            name="single_solid",
            passed=False,
            reason=f"single_solid:expected 1 solid, found {n}",
            evidence={"n_solids": n},
        )
    return GateResult(name="single_solid", passed=True, evidence={"n_solids": n})


@register_verifier("tier1.watertight", version="1.0.0")
def watertight(ctx: VerifyContext) -> GateResult:
    # build123d 0.10.0 exposes `is_valid` as a bool property, not a method;
    # call it only if some other version makes it a method (defensive, since
    # this touched a C++-backed attribute that has changed shape before).
    try:
        attr = ctx.shape.is_valid
        ok = bool(attr()) if callable(attr) else bool(attr)
    except Exception as e:
        return GateResult(
            name="watertight", passed=False, reason=f"watertight:is_valid_raised:{e}"
        )
    if not ok:
        return GateResult(
            name="watertight", passed=False, reason="watertight:is_valid_false"
        )
    return GateResult(name="watertight", passed=True)


@register_verifier("tier1.rebuild_deterministic", version="1.0.0")
def rebuild_deterministic(ctx: VerifyContext) -> GateResult:
    """F2: the same submission built twice must hash identically. A failure
    here means the submission embeds non-determinism (wall-clock time, a
    random seed, iteration over an unordered container) -- never average it
    away as noise (§13.3)."""

    if ctx.geom_hash != ctx.geom_hash_rebuild:
        return GateResult(
            name="rebuild_deterministic",
            passed=False,
            reason="rebuild_deterministic:geom_hash differs across two builds of the same submission",
            evidence={"geom_hash_a": ctx.geom_hash, "geom_hash_b": ctx.geom_hash_rebuild},
        )
    return GateResult(
        name="rebuild_deterministic", passed=True, evidence={"geom_hash": ctx.geom_hash}
    )


@register_verifier("tier1.hole_present", version="1.0.0")
def hole_present(ctx: VerifyContext) -> GateResult:
    """tag_stability family (§8.3): a named hole, declared in the task as
    params={"at": [x, y], "diameter": d, "tolerance": t}, must still be
    found at that position after a rebuild.

    Detection uses the cylindrical face's bounding-box center and radius
    rather than `Face.center()` -- measured in this environment,
    `Face.center()` on a trimmed cylindrical (through-hole) face does not
    return the hole's axis position, while `Face.bounding_box().center()`
    does (confirmed: a 4mm-radius hole at x=20 reported center().X == 16
    via `.center()` but bounding_box().center().X == 20, matching the
    lateral-surface-area cross-check of 2*pi*r*h)."""

    at = ctx.params.get("at")
    diameter = ctx.params.get("diameter")
    if at is None or diameter is None:
        return GateResult(
            name="hole_present",
            passed=False,
            reason="hole_present:task did not declare params.at and params.diameter",
        )
    tolerance = float(ctx.params.get("tolerance", 0.5))
    expected_r = float(diameter) / 2.0

    best = None
    for face in ctx.shape.faces():
        if face.geom_type != GeomType.CYLINDER:
            continue
        bb = face.bounding_box()
        center = bb.center()
        rx = (bb.max.X - bb.min.X) / 2.0
        ry = (bb.max.Y - bb.min.Y) / 2.0
        r = (rx + ry) / 2.0
        dx = abs(center.X - float(at[0]))
        dy = abs(center.Y - float(at[1]))
        dr = abs(r - expected_r)
        if dx <= tolerance and dy <= tolerance and dr <= tolerance:
            best = {"center": [center.X, center.Y, center.Z], "radius": r}
            break

    if best is None:
        return GateResult(
            name="hole_present",
            passed=False,
            reason=(
                f"hole_present:no cylindrical face within tolerance={tolerance} of "
                f"at={at}, diameter={diameter}"
            ),
        )
    return GateResult(name="hole_present", passed=True, evidence=best)


@register_verifier("tier1.mass", version="1.0.0")
def mass_metric(ctx: VerifyContext) -> Metric:
    """mass_g = volume(mm^3) * density(g/mm^3). params={"density_g_per_mm3": d}."""

    density = float(ctx.params.get("density_g_per_mm3", 0.00785))  # mild steel default
    mass_g = float(ctx.shape.volume) * density
    return Metric(name="mass_g", value=mass_g, unit="g")
