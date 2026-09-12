"""§12: anti-gaming gates that must exist before any RL run. A policy
optimizing against a verifier will find whatever the verifier does not
check; these are the specific exploits OF-TR-002 names, each as an
independent, pure, unit-testable function so the RL trainer and any
future eval can call the same checks (R1).
"""

from __future__ import annotations

import ast

from ..contracts import GateResult


def degenerate_geometry_gate(
    shape, min_volume_mm3: float = 1.0, min_wall_mm: float = 0.1
) -> GateResult:
    """Zero/near-zero volume or an unreasonably thin body. Self-
    intersection is already covered by tier1.watertight; this is the
    complementary "technically valid but degenerate" exploit -- a policy
    discovering that a sliver with near-zero volume still satisfies
    single_solid + watertight."""

    volume = float(shape.volume)
    if volume < min_volume_mm3:
        return GateResult(
            name="degenerate_geometry",
            passed=False,
            reason=f"degenerate_geometry:volume {volume:g}mm^3 < floor {min_volume_mm3:g}mm^3",
            evidence={"volume_mm3": volume},
        )

    from ..verify.context import VerifyContext
    from ..verify.tier4_dfm import wall_min_metric

    wall_min = wall_min_metric(VerifyContext(kind="ofl", payload="", shape=shape)).value
    if wall_min > 0 and wall_min < min_wall_mm:
        return GateResult(
            name="degenerate_geometry",
            passed=False,
            reason=f"degenerate_geometry:wall_min {wall_min:g}mm < floor {min_wall_mm:g}mm",
            evidence={"wall_min_mm": wall_min},
        )

    return GateResult(name="degenerate_geometry", passed=True, evidence={"volume_mm3": volume})


def parameter_at_bound(value: float, domain: tuple[float, float], rel_tol: float = 1e-6) -> bool:
    """A policy that always pushes a free parameter to its declared
    min/max (rather than to whatever value the task actually calls for) is
    a classic reward-hacking pattern when a metric's target is one-sided
    (e.g. "mass <= X" is trivially maximized by minimizing every
    dimension to its floor). This flags it; it is the caller's job
    (a task-specific rubric) to decide whether that is expected or
    suspicious for a given check."""

    lo, hi = domain
    span = hi - lo
    if span <= 0:
        return value == lo
    tol = rel_tol * span
    return abs(value - lo) <= tol or abs(value - hi) <= tol


def is_exact_copy(payload: str, forbidden_texts: list[str]) -> bool:
    """"Did it just copy the prompt's example" -- an exact (whitespace-
    normalized) match against a worked example/exemplar the task/prompt
    exposed. Catches the laziest exploit: reproduce the exemplar byte-for-
    byte and let it score on the exemplar's own correctness."""

    normalized_payload = " ".join(payload.split())
    for forbidden in forbidden_texts:
        if normalized_payload == " ".join(forbidden.split()):
            return True
    return False


_FEATURE_CALL_NAMES = {
    "Hole",
    "Sketch",
    "fillet",
    "chamfer",
    "shell",
    "loft",
    "mirror",
    "extrude",
}


def count_features(source: str) -> int:
    """Rough feature-count proxy: number of calls to known OFL/build123d
    feature-producing functions in the submission's AST. A policy that
    wins by emitting thousands of micro-features (each individually legal,
    collectively absurd) is caught by capping this, not by any single
    gate noticing one feature is wrong."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in _FEATURE_CALL_NAMES:
                count += 1
    return count


def feature_count_gate(source: str, max_features: int) -> GateResult:
    n = count_features(source)
    if n > max_features:
        return GateResult(
            name="feature_count",
            passed=False,
            reason=f"feature_count:{n} feature calls exceeds cap {max_features}",
            evidence={"n_features": n},
        )
    return GateResult(name="feature_count", passed=True, evidence={"n_features": n})
