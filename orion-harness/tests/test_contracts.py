import pytest
from pydantic import ValidationError

from orion_harness.contracts import (
    CheckSpec,
    EnvDigest,
    GateResult,
    Result,
    Submission,
    TaskSpec,
)


def test_taskspec_roundtrip():
    task = TaskSpec(
        task_id="t1",
        family="prismatic_plate",
        pillar="reconstruct",
        split="dev",
        difficulty=1,
        prompt="make a plate",
        checks=[CheckSpec(name="schema_valid", verifier="tier0.schema", kind="gate")],
        provenance="hand_authored",
    )
    data = task.model_dump(mode="json")
    assert TaskSpec.model_validate(data) == task


def test_taskspec_rejects_unknown_field():
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(
            {
                "task_id": "t1",
                "family": "f",
                "pillar": "reconstruct",
                "split": "dev",
                "difficulty": 1,
                "prompt": "p",
                "checks": [],
                "provenance": "hand_authored",
                "not_a_real_field": 1,
            }
        )


def test_models_are_frozen():
    task = TaskSpec(
        task_id="t1",
        family="f",
        pillar="reconstruct",
        split="dev",
        difficulty=1,
        prompt="p",
        checks=[],
        provenance="hand_authored",
    )
    with pytest.raises(ValidationError):
        task.task_id = "t2"


def test_result_score_is_none_unless_scored():
    result = Result(
        task_id="t1",
        submission_hash="abc",
        env=EnvDigest(harness_version="0.1.0"),
        status="error",
        error_code="model_api_error",
    )
    assert result.score is None  # R3: never 0.0 as a sentinel for "did not run"


def test_result_rejects_score_without_scored_status_is_not_enforced_by_pydantic_alone():
    # contracts.py cannot forbid `score=1.0, status="error"` via pydantic typing
    # alone -- that invariant is enforced by runner/evaluate.py, which is the
    # single place Results are constructed. This test documents the boundary.
    result = Result(
        task_id="t1",
        submission_hash="abc",
        env=EnvDigest(harness_version="0.1.0"),
        status="scored",
        score=1.0,
        gates=[GateResult(name="g", passed=True)],
    )
    assert result.score == 1.0


def test_submission_requires_known_kind():
    with pytest.raises(ValidationError):
        Submission(task_id="t1", kind="not_a_kind", payload="x")
