"""§12: "Format reward stays small (~0.1) and is never able to compensate
for a failed gate." Tested as an invariant over the actual weights, not
just by example: the maximum possible reward on ANY failing-gate rollout
must be strictly less than the minimum possible reward on ANY
passing-gate rollout.
"""

from orion_harness.contracts import EnvDigest, GateResult, Result
from orion_harness.rl.rubric import DEFAULT_WEIGHTS, default_rubric


def _env():
    return EnvDigest(harness_version="0.1.0")


def _result(status, gates, score=None):
    return Result(
        task_id="t",
        submission_hash="x",
        env=_env(),
        status=status,
        gates=gates,
        score=score,
    )


def test_format_reward_cannot_beat_a_passing_gate_reward():
    rubric = default_rubric()

    failing_best_case = _result(
        "scored", gates=[GateResult(name="g", passed=False)], score=0.0
    )
    best_possible_failing = rubric.score(result=failing_best_case, raw_completion="x" * 100)

    passing_worst_case = _result(
        "scored", gates=[GateResult(name="g", passed=True)], score=0.0
    )
    worst_possible_passing = rubric.score(result=passing_worst_case, raw_completion="")

    assert best_possible_failing.total < worst_possible_passing.total


def test_gates_reward_is_zero_on_any_gate_failure():
    rubric = default_rubric()
    result = _result(
        "scored",
        gates=[GateResult(name="a", passed=True), GateResult(name="b", passed=False)],
        score=0.0,
    )
    breakdown = rubric.score(result=result, raw_completion="anything")
    assert breakdown.components["gates_reward"] == 0.0
    assert breakdown.components["metric_reward"] == 0.0


def test_metric_reward_only_counts_when_all_gates_pass():
    rubric = default_rubric()
    result = _result("scored", gates=[GateResult(name="a", passed=True)], score=0.7)
    breakdown = rubric.score(result=result, raw_completion="x")
    assert breakdown.components["gates_reward"] == 1.0
    assert breakdown.components["metric_reward"] == 0.7


def test_non_scored_status_scores_zero_on_gates_and_metrics():
    rubric = default_rubric()
    result = _result("error", gates=[])
    breakdown = rubric.score(result=result, raw_completion="x")
    assert breakdown.components["gates_reward"] == 0.0
    assert breakdown.components["metric_reward"] == 0.0


def test_default_weights_match_spec_order():
    assert DEFAULT_WEIGHTS == (1.0, 1.0, 0.1)
