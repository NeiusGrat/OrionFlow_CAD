"""M2 acceptance (§14): "the current model scores strictly between 0.15
and 0.85" on `frozen`, and "every gate has at least one task that fails it
and one that passes it."

This repo has no live model adapter wired up yet (§11 is not milestoned
for M1/M2 -- see the session report for why), so there is no real model to
run this against. This test is an honest stand-in: a synthetic "half-broken
submitter" that answers half of `frozen` correctly (the oracle) and half
incorrectly (a generic single_solid-breaking mutation, regardless of the
target task's own style) -- enough to demonstrate the suite actually has
discriminative power, without claiming a live eval was run.
"""

from pathlib import Path

import pytest

from orion_harness.contracts import EnvDigest, Submission
from orion_harness.runner.cache import ResultCache
from orion_harness.runner.evaluate import evaluate_submission
from orion_harness.runner.pool import WorkerPool
from orion_harness.tasks.loader import load_split

from conftest import ORACLES_ROOT, TASKS_ROOT

BROKEN_SOURCE = (ORACLES_ROOT / "mutations" / "single_solid_fails.ofl.py").read_text(
    encoding="utf-8"
)


def _oracle_submission(task_id: str) -> Submission:
    for ext, kind in ((".ofl.py", "ofl"), (".b123d.py", "build123d"), (".json", "featuregraph")):
        path = ORACLES_ROOT / f"{task_id}{ext}"
        if path.exists():
            return Submission(task_id=task_id, kind=kind, payload=path.read_text(encoding="utf-8"))
    raise AssertionError(f"no oracle for {task_id}")


def _broken_submission(task_id: str) -> Submission:
    return Submission(task_id=task_id, kind="ofl", payload=BROKEN_SOURCE)


def test_synthetic_half_broken_submitter_lands_in_the_target_band(tmp_path):
    tasks = load_split(TASKS_ROOT, "frozen")
    assert len(tasks) >= 10, "need enough frozen tasks for this to be meaningful"

    env = EnvDigest(harness_version="0.1.0")
    cache = ResultCache(tmp_path / "cache")
    scores = []
    gate_seen_pass: set[str] = set()
    gate_seen_fail: set[str] = set()

    with WorkerPool(n_workers=2) as pool:
        for i, task in enumerate(tasks):
            submission = _oracle_submission(task.task_id) if i % 2 == 0 else _broken_submission(
                task.task_id
            )
            result = evaluate_submission(task, submission, pool, cache, env)
            if result.status == "scored" and result.score is not None:
                scores.append(result.score)
            for g in result.gates:
                (gate_seen_pass if g.passed else gate_seen_fail).add(g.name)

    mean_score = sum(scores) / len(scores)
    assert 0.15 < mean_score < 0.85, (
        f"suite is saturated or floored at this mix (mean={mean_score}) -- "
        f"not the measurement failure mode OF-TR-002 §0.2 warns about, but "
        f"worth re-checking the mix ratio if this ever fails"
    )

    # single_solid is the gate the synthetic "broken" half always fails;
    # schema_valid/watertight/rebuild_deterministic are seen passing on the
    # oracle half. Demonstrating both sides of at least one real gate is the
    # point -- the mutation test suite (test_mutations.py) already proves
    # each gate individually fails for the right reason.
    assert "single_solid" in gate_seen_pass
    assert "single_solid" in gate_seen_fail
