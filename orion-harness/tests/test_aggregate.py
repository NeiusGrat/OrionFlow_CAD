from orion_harness.contracts import EnvDigest, GateResult, Result, TaskSpec
from orion_harness.score.aggregate import pass_at_k, summarize


def _task(task_id, family):
    return TaskSpec(
        task_id=task_id,
        family=family,
        pillar="modify",
        split="dev",
        difficulty=1,
        prompt="p",
        checks=[],
        provenance="hand_authored",
    )


def _env():
    return EnvDigest(harness_version="0.1.0")


def _result(task_id, status, score=None, gates=None, wall_s=1.0):
    return Result(
        task_id=task_id,
        submission_hash="x",
        env=_env(),
        status=status,
        score=score,
        gates=gates or [],
        wall_s=wall_s,
    )


def test_summarize_status_counts_and_family_breakdown():
    tasks = {
        "a": _task("a", "fam1"),
        "b": _task("b", "fam1"),
        "c": _task("c", "fam2"),
    }
    results = [
        _result("a", "scored", score=1.0),
        _result("b", "scored", score=0.0),
        _result("c", "error"),
    ]
    summary = summarize(tasks, results)
    assert summary.n_total == 3
    assert summary.status_counts == {"scored": 2, "error": 1}
    assert summary.overall_mean_score == 0.5

    fam1 = next(f for f in summary.by_family if f.family == "fam1")
    assert fam1.n == 2
    assert fam1.mean_score == 0.5
    fam2 = next(f for f in summary.by_family if f.family == "fam2")
    assert fam2.n_scored == 0
    assert fam2.mean_score is None  # never 0.0 as a sentinel


def test_summarize_gate_failure_counts():
    tasks = {"a": _task("a", "fam1"), "b": _task("b", "fam1")}
    results = [
        _result(
            "a",
            "scored",
            score=0.0,
            gates=[GateResult(name="watertight", passed=False)],
        ),
        _result(
            "b",
            "scored",
            score=1.0,
            gates=[GateResult(name="watertight", passed=True)],
        ),
    ]
    summary = summarize(tasks, results)
    wt = next(g for g in summary.gate_failures if g.gate_name == "watertight")
    assert wt.n_seen == 2
    assert wt.n_failed == 1


def test_pass_at_1_all_pass_and_all_fail():
    assert pass_at_k({"t1": [1.0] * 5}, k=1) == 1.0
    assert pass_at_k({"t1": [0.0] * 5}, k=1) == 0.0


def test_pass_at_k_matches_unbiased_estimator_hand_computation():
    # n=5 samples, c=2 passing, k=1 -> 1 - C(3,1)/C(5,1) = 1 - 3/5 = 0.4
    result = pass_at_k({"t1": [1.0, 1.0, 0.0, 0.0, 0.0]}, k=1)
    assert result == 0.4


def test_pass_at_k_raises_when_fewer_samples_than_k():
    import pytest

    with pytest.raises(ValueError):
        pass_at_k({"t1": [1.0, 0.0]}, k=5)
