"""Worker-side job dispatch: build + run a task's *declared* checks, in one
process. This is what actually runs inside a pool worker. pool.py sends a
plain dict job over a Pipe and gets back a plain dict result -- nothing
but JSON-safe data crosses the pipe, because OCCT shape objects are neither
reliably picklable nor worth moving across a process boundary.

Tier short-circuiting (§7.2): stop at the first failed gate and mark the
rest skipped. A shape is built at most twice per job -- once, and a second
time only if some check in the task actually needs rebuild_deterministic
-- never eagerly, so a task with no determinism check pays for one build,
not two.
"""

from __future__ import annotations

from ..contracts import CheckSpec, GateResult, Metric
from ..execute.build123d_source import build_build123d
from ..execute.canonical import geom_hash as _geom_hash
from ..execute.featuregraph import build_featuregraph
from ..execute.ofl import build_ofl
from ..registry import get_verifier
from ..score.rubric import score_metrics
from ..verify import (  # noqa: F401 -- registers verifiers
    tier0_grammar,
    tier1_geometry,
    tier3_physics,
    tier4_dfm,
)
from ..verify.context import VerifyContext
from .errors import TaskOutcome

NEEDS_SHAPE = {
    "tier1.single_solid",
    "tier1.watertight",
    "tier1.hole_present",
    "tier1.mass",
    "tier4.wall_min",
    "tier4.accessibility",
    "tier4.setups",
}
NEEDS_REBUILD = {"tier1.rebuild_deterministic"}


def _build(kind: str, payload):
    if kind == "ofl":
        return build_ofl(payload)
    if kind == "featuregraph":
        return build_featuregraph(payload)
    if kind == "build123d":
        return build_build123d(payload)
    raise TaskOutcome(code="parse_error", reason=f"unsupported submission kind {kind!r}")


def _ensure_shape(ctx: VerifyContext, kind: str, payload) -> None:
    if ctx.shape is None:
        ctx.shape = _build(kind, payload)
        ctx.geom_hash = _geom_hash(ctx.shape)


def _ensure_rebuild(ctx: VerifyContext, kind: str, payload) -> None:
    if ctx.shape_rebuild is None:
        ctx.shape_rebuild = _build(kind, payload)
        ctx.geom_hash_rebuild = _geom_hash(ctx.shape_rebuild)


def run_build_job(kind: str, payload, checks: list[dict]) -> dict:
    """`checks` is `[c.model_dump() for c in task.checks]` -- plain dicts,
    because this runs inside a spawned worker and only JSON-safe data
    should cross the pipe back.

    Returns {"gates": [...], "metrics": [...], "skipped": [...],
    "geom_hash": str|None, "score": float}. Raises TaskOutcome if
    execution itself fails (caught by pool.py's worker loop)."""

    ctx = VerifyContext(kind=kind, payload=payload)
    gate_results: list[GateResult] = []
    skipped: list[str] = []

    gate_checks = [c for c in checks if c["kind"] == "gate"]
    metric_checks = [c for c in checks if c["kind"] == "metric"]

    failed = False
    for check in gate_checks:
        if failed:
            skipped.append(check["name"])
            continue

        verifier_key = check["verifier"]
        if verifier_key in NEEDS_SHAPE or verifier_key in NEEDS_REBUILD:
            _ensure_shape(ctx, kind, payload)
        if verifier_key in NEEDS_REBUILD:
            _ensure_rebuild(ctx, kind, payload)

        ctx.params = check.get("params", {})
        result = get_verifier(verifier_key).fn(ctx)
        result = result.model_copy(update={"name": check["name"]})
        gate_results.append(result)
        if not result.passed:
            failed = True

    if failed:
        return {
            "gates": [g.model_dump() for g in gate_results],
            "metrics": [],
            "skipped": skipped,
            "geom_hash": ctx.geom_hash,
            "score": 0.0,
        }

    metric_results: list[Metric] = []
    for check in metric_checks:
        verifier_key = check["verifier"]
        if verifier_key in NEEDS_SHAPE or verifier_key in NEEDS_REBUILD:
            _ensure_shape(ctx, kind, payload)
        ctx.params = check.get("params", {})
        raw_metric = get_verifier(verifier_key).fn(ctx)
        check_spec = CheckSpec.model_validate(check)
        from ..score.rubric import metric_unit_score

        s, slack = metric_unit_score(check_spec, raw_metric.value)
        metric_results.append(
            raw_metric.model_copy(
                update={"name": check["name"], "target": check_spec.target, "slack": slack}
            )
        )

    score = score_metrics([CheckSpec.model_validate(c) for c in checks], metric_results)

    return {
        "gates": [g.model_dump() for g in gate_results],
        "metrics": [m.model_dump() for m in metric_results],
        "skipped": skipped,
        "geom_hash": ctx.geom_hash,
        "score": score,
    }
