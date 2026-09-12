"""§12 RL interface acceptance: a rollout executes end to end with reward
computed by the same verifier the eval uses (evaluate_submission). Not a
GRPO training run (no RL trainer or GPU in this session) -- this is the
environment's own `rollout()` call, exercised directly.
"""

import pytest

from orion_harness.contracts import CheckSpec, Submission, TaskSpec
from orion_harness.rl.env import load_environment
from orion_harness.rl.env import _strip_physics_checks

from conftest import ORACLES_ROOT, TASKS_ROOT


@pytest.fixture(scope="module")
def env():
    environment = load_environment(str(TASKS_ROOT), split="dev", n_workers=1)
    yield environment
    environment.close()


def test_rollout_on_oracle_submission_scores_full_reward(env):
    task_id = "flat_plate"
    payload = (ORACLES_ROOT / "flat_plate.ofl.py").read_text(encoding="utf-8")
    submission = Submission(task_id=task_id, kind="ofl", payload=payload)

    rollout = env.rollout(task_id, submission)
    assert rollout.result.status == "scored"
    assert rollout.reward.components["gates_reward"] == 1.0
    assert rollout.reward.total >= 1.0


def test_rollout_on_broken_submission_scores_small_reward(env):
    task_id = "flat_plate"
    broken = (ORACLES_ROOT / "mutations" / "single_solid_fails.ofl.py").read_text(
        encoding="utf-8"
    )
    submission = Submission(task_id=task_id, kind="ofl", payload=broken)

    rollout = env.rollout(task_id, submission)
    assert rollout.reward.components["gates_reward"] == 0.0
    assert rollout.reward.components["metric_reward"] == 0.0
    assert rollout.reward.total < 0.2  # format_reward capped at weight 0.1


def test_rollout_on_unknown_task_id_raises(env):
    with pytest.raises(KeyError):
        env.rollout("not_a_real_task", Submission(task_id="x", kind="ofl", payload="part = None"))


def test_strip_physics_checks_removes_only_tier3():
    task = TaskSpec(
        task_id="t",
        family="bracket_gusseted",
        pillar="design",
        split="dev",
        difficulty=1,
        prompt="p",
        checks=[
            CheckSpec(name="schema_valid", verifier="tier0.schema", kind="gate"),
            CheckSpec(name="fos", verifier="tier3.static", kind="gate"),
        ],
        provenance="hand_authored",
    )
    stripped = _strip_physics_checks(task)
    assert [c.verifier for c in stripped.checks] == ["tier0.schema"]
    # original task is untouched (model_copy, not mutation)
    assert len(task.checks) == 2


def test_fidelity_must_be_fast_or_full():
    with pytest.raises(ValueError):
        load_environment(str(TASKS_ROOT), split="dev", fidelity="bogus", n_workers=1)
