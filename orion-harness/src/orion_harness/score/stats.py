"""§9.3 uncertainty. Bootstrap CI is the default over 60-150 item suites
(CLT intervals are unreliable at that size -- Miller, arXiv:2411.00640);
clustered resampling accounts for variants of one master part not being
independent samples; paired deltas remove per-task difficulty variance
from a model-vs-model comparison "for free" by differencing on the same
tasks. The report layer (report/render.py) refuses to print a bare mean
without calling into this module first (R10).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import NormalDist

_NORMAL = NormalDist()


@dataclass
class Interval:
    point: float
    lo: float
    hi: float
    alpha: float
    n_resamples: int


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo_idx = int(idx)
    hi_idx = min(lo_idx + 1, len(sorted_values) - 1)
    frac = idx - lo_idx
    return sorted_values[lo_idx] * (1 - frac) + sorted_values[hi_idx] * frac


def bootstrap_ci(
    values: list[float],
    n_resamples: int = 10000,
    alpha: float = 0.05,
    rng: random.Random | None = None,
) -> Interval:
    """Unclustered bootstrap over independent items (e.g. distinct task
    families each contributing one task). For a suite with correlated
    variants of one master part, use `clustered_bootstrap_ci` instead."""

    if not values:
        raise ValueError("cannot bootstrap an empty sample")
    rng = rng or random.Random()
    n = len(values)
    point = sum(values) / n
    means = []
    for _ in range(n_resamples):
        resample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(resample) / n)
    means.sort()
    lo = _percentile(means, alpha / 2)
    hi = _percentile(means, 1 - alpha / 2)
    return Interval(point=point, lo=lo, hi=hi, alpha=alpha, n_resamples=n_resamples)


def clustered_bootstrap_ci(
    values_by_cluster: dict[str, list[float]],
    n_resamples: int = 10000,
    alpha: float = 0.05,
    rng: random.Random | None = None,
) -> Interval:
    """Two-stage bootstrap (§9.3): resample clusters (families) with
    replacement, then resample tasks within each resampled cluster with
    replacement. Variants of one master part are correlated; naive
    per-task SEs can understate uncertainty by up to ~3x (Miller)."""

    clusters = [v for v in values_by_cluster.values() if v]
    if not clusters:
        raise ValueError("cannot bootstrap an empty sample")
    rng = rng or random.Random()
    all_values = [v for cluster in clusters for v in cluster]
    point = sum(all_values) / len(all_values)

    n_clusters = len(clusters)
    means = []
    for _ in range(n_resamples):
        resampled_values: list[float] = []
        for _ in range(n_clusters):
            cluster = clusters[rng.randrange(n_clusters)]
            n_items = len(cluster)
            resampled_values.extend(cluster[rng.randrange(n_items)] for _ in range(n_items))
        means.append(sum(resampled_values) / len(resampled_values))
    means.sort()
    lo = _percentile(means, alpha / 2)
    hi = _percentile(means, 1 - alpha / 2)
    return Interval(point=point, lo=lo, hi=hi, alpha=alpha, n_resamples=n_resamples)


def paired_delta_ci(
    scores_a: dict[str, float],
    scores_b: dict[str, float],
    n_resamples: int = 10000,
    alpha: float = 0.05,
    rng: random.Random | None = None,
) -> Interval:
    """§9.3: bootstrap the per-task difference B - A over tasks common to
    both runs. Pairing removes task-difficulty variance for free -- this is
    why `compare` reports Delta [CI] rather than two separate means."""

    common = sorted(set(scores_a) & set(scores_b))
    if not common:
        raise ValueError("no tasks in common between the two runs")
    diffs = [scores_b[t] - scores_a[t] for t in common]
    return bootstrap_ci(diffs, n_resamples=n_resamples, alpha=alpha, rng=rng)


def minimum_detectable_effect(
    n: int, sd: float, alpha: float = 0.05, power: float = 0.8
) -> float:
    """§9.3 power/MDE helper, normal-approximation (paired-difference
    design: `n` tasks, each contributing one paired delta with standard
    deviation `sd`). This is a sizing tool, not a reporting tool -- actual
    run summaries still use the bootstrap, never this normal approximation,
    per R10 and the CLT caveat in Miller."""

    if n <= 0 or sd < 0:
        raise ValueError("n must be > 0 and sd must be >= 0")
    z_alpha = _NORMAL.inv_cdf(1 - alpha / 2)
    z_power = _NORMAL.inv_cdf(power)
    return (z_alpha + z_power) * sd / (n**0.5)
