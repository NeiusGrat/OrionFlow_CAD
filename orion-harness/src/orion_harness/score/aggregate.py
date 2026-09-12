"""§9.4 mandatory breakdowns + §9.2 pass@k. Pure post-processing over a
list of Result + TaskSpec -- no I/O, so it is reusable by the CLI report
renderer, tests, and the RL environment's logging without any of them
owning a second copy of this arithmetic (R1).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import comb

from ..contracts import Result, TaskSpec


@dataclass
class FamilySummary:
    family: str
    n: int
    n_scored: int
    mean_score: float | None  # None if n_scored == 0 -- never 0.0 as a sentinel
    status_counts: dict[str, int]


@dataclass
class GateFailureCount:
    gate_name: str
    n_failed: int
    n_seen: int


@dataclass
class RunSummary:
    n_total: int
    status_counts: dict[str, int]
    overall_mean_score: float | None
    by_family: list[FamilySummary]
    gate_failures: list[GateFailureCount]
    median_wall_s: float
    p95_wall_s: float


def _count_statuses(results: list[Result]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for r in results:
        counts[r.status] += 1
    return dict(counts)


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def summarize(tasks_by_id: dict[str, TaskSpec], results: list[Result]) -> RunSummary:
    status_counts: dict[str, int] = defaultdict(int)
    by_family_results: dict[str, list[Result]] = defaultdict(list)
    gate_seen: dict[str, int] = defaultdict(int)
    gate_failed: dict[str, int] = defaultdict(int)
    wall_times: list[float] = []

    for r in results:
        status_counts[r.status] += 1
        wall_times.append(r.wall_s)
        task = tasks_by_id.get(r.task_id)
        family = task.family if task else "unknown"
        by_family_results[family].append(r)
        for g in r.gates:
            gate_seen[g.name] += 1
            if not g.passed:
                gate_failed[g.name] += 1

    scored = [r.score for r in results if r.status == "scored" and r.score is not None]
    overall_mean = (sum(scored) / len(scored)) if scored else None

    by_family = []
    for family, frs in sorted(by_family_results.items()):
        fscored = [r.score for r in frs if r.status == "scored" and r.score is not None]
        by_family.append(
            FamilySummary(
                family=family,
                n=len(frs),
                n_scored=len(fscored),
                mean_score=(sum(fscored) / len(fscored)) if fscored else None,
                status_counts=_count_statuses(frs),
            )
        )

    gate_failures = [
        GateFailureCount(
            gate_name=name, n_failed=gate_failed.get(name, 0), n_seen=gate_seen[name]
        )
        for name in sorted(gate_seen)
    ]

    wall_sorted = sorted(wall_times)
    return RunSummary(
        n_total=len(results),
        status_counts=dict(status_counts),
        overall_mean_score=overall_mean,
        by_family=by_family,
        gate_failures=gate_failures,
        median_wall_s=_percentile(wall_sorted, 0.5),
        p95_wall_s=_percentile(wall_sorted, 0.95),
    )


def _unbiased_pass_at_k(n: int, c: int, k: int) -> float:
    """The standard HumanEval/Codex estimator: 1 - C(n-c, k) / C(n, k)."""

    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_at_k(scores_by_task: dict[str, list[float]], k: int, threshold: float = 1.0) -> float:
    """§9.2. `scores_by_task` maps task_id -> per-sample scores from one run
    with >= k samples per task. Callers must exclude `error`-status samples
    before calling this (R3: infra failures are not zero scores and must
    not be folded into a denominator here either)."""

    if k < 1:
        raise ValueError("k must be >= 1")
    per_task = []
    for task_id, scores in scores_by_task.items():
        n = len(scores)
        if n < k:
            raise ValueError(f"task {task_id!r} has only {n} samples, need >= k={k}")
        c = sum(1 for s in scores if s >= threshold)
        per_task.append(_unbiased_pass_at_k(n, c, k))
    return sum(per_task) / len(per_task) if per_task else 0.0
