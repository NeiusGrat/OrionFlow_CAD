"""§9.1 scoring math. Pure arithmetic -- no geometry, no worker pool."""

import pytest

from orion_harness.contracts import CheckSpec, Metric
from orion_harness.score.rubric import metric_unit_score, score_metrics


def _check(name, target, weight=1.0):
    return CheckSpec(name=name, verifier="tier1.mass", kind="metric", target=target, weight=weight)


def test_no_metric_checks_scores_one():
    assert score_metrics([CheckSpec(name="g", verifier="tier0.schema", kind="gate")], []) == 1.0


def test_min_target_full_credit_above_threshold():
    s, slack = metric_unit_score(_check("fos", {"min": 2.0}), 4.0)
    assert s == 1.0
    assert slack > 0


def test_min_target_partial_credit_below_threshold():
    s, slack = metric_unit_score(_check("fos", {"min": 2.0}), 1.0)
    assert s == 0.5
    assert slack < 0  # violated


def test_max_target_full_credit_below_threshold():
    s, slack = metric_unit_score(_check("mass_g", {"max": 2000}), 1000)
    assert s == 1.0
    assert slack > 0


def test_max_target_partial_credit_above_threshold():
    s, slack = metric_unit_score(_check("mass_g", {"max": 1000}), 2000)
    assert s == 0.5
    assert slack < 0


def test_equals_target_tolerance():
    s_ok, _ = metric_unit_score(_check("setups", {"equals": 2, "tolerance": 0.001}), 2.0)
    s_bad, _ = metric_unit_score(_check("setups", {"equals": 2, "tolerance": 0.001}), 3.0)
    assert s_ok == 1.0
    assert s_bad == 0.0


def test_weighted_aggregate_matches_hand_computation():
    checks = [
        _check("fos", {"min": 2.0}, weight=0.6),
        _check("mass_g", {"max": 2000}, weight=0.4),
    ]
    metrics = [Metric(name="fos", value=4.0, unit=""), Metric(name="mass_g", value=1000, unit="g")]
    # both checks at full credit (s=1.0 each) -> weighted sum = 1.0
    assert score_metrics(checks, metrics) == pytest.approx(1.0)

    metrics_half = [
        Metric(name="fos", value=1.0, unit=""),  # s=0.5
        Metric(name="mass_g", value=1000, unit="g"),  # s=1.0
    ]
    # 0.6*0.5 + 0.4*1.0 = 0.7
    assert score_metrics(checks, metrics_half) == pytest.approx(0.7)


def test_weights_are_normalized_not_assumed_to_sum_to_one():
    checks = [_check("a", {"min": 1.0}, weight=2.0), _check("b", {"min": 1.0}, weight=2.0)]
    metrics = [Metric(name="a", value=1.0, unit=""), Metric(name="b", value=0.5, unit="")]
    # s_a=1.0, s_b=0.5; weights 2 and 2 normalize to 0.5/0.5 -> 0.75
    assert score_metrics(checks, metrics) == pytest.approx(0.75)


def test_zero_total_weight_is_an_error():
    checks = [_check("a", {"min": 1.0}, weight=0.0)]
    with pytest.raises(ValueError):
        score_metrics(checks, [Metric(name="a", value=1.0, unit="")])


def test_missing_measured_value_is_an_error():
    checks = [_check("a", {"min": 1.0}, weight=1.0)]
    with pytest.raises(ValueError):
        score_metrics(checks, [])
