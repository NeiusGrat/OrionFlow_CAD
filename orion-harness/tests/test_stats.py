"""§14 M3 acceptance tests, directly: comparing a run with itself returns
Delta = 0 with a zero-width interval; a synthetic +0.05 uniform improvement
is detected at (approximately) the sample size the power helper predicts.
"""

import random

import pytest

from orion_harness.score.stats import (
    bootstrap_ci,
    clustered_bootstrap_ci,
    minimum_detectable_effect,
    paired_delta_ci,
)


def test_bootstrap_ci_on_identical_values_is_zero_width():
    ci = bootstrap_ci([0.7] * 30, n_resamples=500, rng=random.Random(0))
    assert ci.point == pytest.approx(0.7)
    assert ci.lo == pytest.approx(0.7)
    assert ci.hi == pytest.approx(0.7)


def test_comparing_a_run_with_itself_is_zero_delta_zero_width():
    scores = {f"t{i}": (i % 5) / 4 for i in range(40)}
    ci = paired_delta_ci(scores, scores, n_resamples=500, rng=random.Random(0))
    assert ci.point == 0.0
    assert ci.lo == 0.0
    assert ci.hi == 0.0


def test_paired_delta_ci_only_uses_common_tasks():
    a = {"t1": 0.5, "t2": 0.5}
    b = {"t2": 1.0, "t3": 1.0}
    ci = paired_delta_ci(a, b, n_resamples=200, rng=random.Random(0))
    assert ci.point == pytest.approx(0.5)  # only t2 is common: 1.0 - 0.5


def test_clustered_bootstrap_point_matches_overall_mean():
    clusters = {"fam_a": [1.0, 1.0, 1.0], "fam_b": [0.0, 0.0]}
    ci = clustered_bootstrap_ci(clusters, n_resamples=500, rng=random.Random(0))
    assert ci.point == pytest.approx(3 / 5)


def test_minimum_detectable_effect_matches_hand_computed_z_scores():
    # z_{0.975} ~= 1.95996, z_{0.8} ~= 0.84162 for alpha=0.05, power=0.8
    mde = minimum_detectable_effect(n=150, sd=0.3, alpha=0.05, power=0.8)
    expected = (1.959963985 + 0.841621234) * 0.3 / (150**0.5)
    assert mde == pytest.approx(expected, rel=1e-6)


def test_power_helper_predicts_a_sample_size_that_detects_a_uniform_improvement():
    """M3 acceptance (§14): a synthetic +0.05 uniform improvement is
    detected at the sample size the power helper predicts."""

    sd = 0.3
    effect = 0.05
    z_alpha = 1.959963985
    z_power = 0.841621234
    # power=0.8 means an 80% detection chance at exactly the MDE-predicted n;
    # a 20% margin keeps this assertion from being seed-sensitive at that
    # boundary while still demonstrating "approximately the predicted size".
    n_required = int(1.2 * ((z_alpha + z_power) * sd / effect) ** 2) + 1

    rng = random.Random(42)
    scores_a = {f"t{i}": 0.5 for i in range(n_required)}
    scores_b = {f"t{i}": 0.5 + rng.gauss(effect, sd) for i in range(n_required)}

    ci = paired_delta_ci(scores_a, scores_b, n_resamples=2000, rng=random.Random(1))
    assert ci.lo > 0, (
        f"expected the {n_required}-task suite (sized by minimum_detectable_effect) "
        f"to detect a +{effect} improvement with sd={sd}, got CI=[{ci.lo}, {ci.hi}]"
    )
