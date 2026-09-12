"""§9.1 per-task scoring. Gates are binary and ordered; metrics are
continuous and only mean anything once every gate has passed (R2) -- the
caller (runner/jobs.py) is responsible for never calling into this module
when a gate has failed; this module has no gate-awareness of its own and
will happily compute a "score" for metrics that should never have been
measured.
"""

from __future__ import annotations

from ..contracts import CheckSpec, Metric


def metric_unit_score(check: CheckSpec, value: float) -> tuple[float, float]:
    """Map a raw metric value to (s in [0,1], slack). slack is normalized
    and negative when the constraint is violated (§5 Metric docstring)."""

    target = check.target or {}
    if "min" in target:
        t = float(target["min"])
        s = max(0.0, min(1.0, value / t)) if t != 0 else (1.0 if value >= 0 else 0.0)
        slack = (value - t) / abs(t) if t != 0 else value
        return s, slack
    if "max" in target:
        t = float(target["max"])
        s = max(0.0, min(1.0, t / value)) if value != 0 else 1.0
        slack = (t - value) / abs(t) if t != 0 else -value
        return s, slack
    if "equals" in target:
        t = float(target["equals"])
        tol = float(target.get("tolerance", 1e-6))
        diff = abs(value - t)
        s = 1.0 if diff <= tol else 0.0
        slack = (tol - diff) / (abs(t) if t != 0 else 1.0)
        return s, slack
    raise ValueError(f"metric check {check.name!r} has no usable target: {target!r}")


def score_metrics(checks: list[CheckSpec], metrics: list[Metric]) -> float:
    """§9.1: score = sum(w_i * s_i) over metric checks, sum(w_i) == 1.
    Returns 1.0 for an all-gates task (no metric checks) -- that is the
    base case, not a special case: a task with nothing to weight has
    nothing left to lose points on once its gates pass."""

    metric_checks = [c for c in checks if c.kind == "metric"]
    if not metric_checks:
        return 1.0

    total_weight = sum(c.weight for c in metric_checks)
    if total_weight <= 0:
        raise ValueError("metric checks declared with zero total weight")

    by_name = {m.name: m.value for m in metrics}
    score = 0.0
    for c in metric_checks:
        if c.name not in by_name:
            raise ValueError(f"no measured value for declared metric check {c.name!r}")
        s, _slack = metric_unit_score(c, by_name[c.name])
        score += (c.weight / total_weight) * s
    return score
