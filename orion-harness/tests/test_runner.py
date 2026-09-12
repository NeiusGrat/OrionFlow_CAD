"""M1 acceptance (§14): a submission that crashes the kernel is recorded as
exec_crash, not as a harness error; three identical runs produce identical
results; the cache is keyed on content, not on run identity (R4).
"""

import time

import pytest

from orion_harness.contracts import CheckSpec, EnvDigest, Submission, TaskSpec
from orion_harness.runner.cache import ResultCache, cache_key
from orion_harness.runner.evaluate import evaluate_submission
from orion_harness.runner.isolate import NetworkAccessDisabled, block_network
from orion_harness.runner.pool import WorkerPool

from conftest import ORACLES_ROOT


def _task(timeout_s: int = 30) -> TaskSpec:
    return TaskSpec(
        task_id="crash_probe",
        family="feature_coverage",
        pillar="modify",
        split="dev",
        difficulty=1,
        prompt="n/a -- test fixture",
        checks=[
            CheckSpec(name="schema_valid", verifier="tier0.schema", kind="gate"),
            CheckSpec(name="single_solid", verifier="tier1.single_solid", kind="gate"),
            CheckSpec(name="watertight", verifier="tier1.watertight", kind="gate"),
            CheckSpec(
                name="rebuild_deterministic",
                verifier="tier1.rebuild_deterministic",
                kind="gate",
            ),
        ],
        timeout_s=timeout_s,
        provenance="hand_authored",
    )


def _submission(task_id: str, source: str) -> Submission:
    return Submission(task_id=task_id, kind="ofl", payload=source, model_id="test")


@pytest.fixture(scope="module")
def pool():
    with WorkerPool(n_workers=1) as p:
        yield p


def test_exec_crash_is_not_a_harness_error(pool, tmp_path):
    task = _task()
    source = (ORACLES_ROOT / "mutations" / "exec_crash_fillet.ofl.py").read_text(
        encoding="utf-8"
    )
    cache = ResultCache(tmp_path / "cache")
    result = evaluate_submission(
        task, _submission(task.task_id, source), pool, cache, EnvDigest(harness_version="0.1.0")
    )
    assert result.status == "invalid"  # the model's fault, not ours (§6.3)
    assert result.error_code == "exec_crash"
    assert result.score is None  # R3: never 0.0 as a sentinel


def test_worker_survives_a_crash_and_serves_the_next_job(pool, tmp_path):
    crash_task = _task()
    crash_source = (ORACLES_ROOT / "mutations" / "exec_crash_fillet.ofl.py").read_text(
        encoding="utf-8"
    )
    ok_task = _task()
    ok_task = ok_task.model_copy(update={"task_id": "flat_plate_probe"})
    ok_source = (ORACLES_ROOT / "flat_plate.ofl.py").read_text(encoding="utf-8")

    cache = ResultCache(tmp_path / "cache")
    env = EnvDigest(harness_version="0.1.0")

    crash_result = evaluate_submission(
        crash_task, _submission(crash_task.task_id, crash_source), pool, cache, env
    )
    ok_result = evaluate_submission(
        ok_task, _submission(ok_task.task_id, ok_source), pool, cache, env
    )

    assert crash_result.error_code == "exec_crash"
    assert ok_result.status == "scored"
    assert ok_result.score == 1.0


def test_cache_hit_on_identical_submission_and_miss_on_changed_payload(pool, tmp_path):
    task = _task()
    source = (ORACLES_ROOT / "flat_plate.ofl.py").read_text(encoding="utf-8")
    cache = ResultCache(tmp_path / "cache")
    env = EnvDigest(harness_version="0.1.0")

    r1 = evaluate_submission(task, _submission(task.task_id, source), pool, cache, env)
    assert r1.cached is False
    r2 = evaluate_submission(task, _submission(task.task_id, source), pool, cache, env)
    assert r2.cached is True
    assert r2.score == r1.score

    changed = source + "\n# a harmless comment that changes the payload\n"
    key_before = cache_key(task, source, {c.verifier: "1.0.0" for c in task.checks}, env)
    key_after = cache_key(task, changed, {c.verifier: "1.0.0" for c in task.checks}, env)
    assert key_before != key_after  # R4: never a cache hit on different content


def test_timeout_is_reported_and_does_not_hang(tmp_path):
    task = _task(timeout_s=1)
    # A pool of its own: this test deliberately kills a worker via timeout
    # and must not poison the shared `pool` fixture used by other tests.
    busy_loop_source = (
        "from orionflow_ofl import *\n"
        "import time\n"
        "time.sleep(5)\n"
        "part = Sketch(Plane.XY).rect(10, 10).extrude(1)\n"
    )
    with WorkerPool(n_workers=1) as solo_pool:
        cache = ResultCache(tmp_path / "cache_timeout")
        env = EnvDigest(harness_version="0.1.0")
        start = time.monotonic()
        result = evaluate_submission(
            task, _submission(task.task_id, busy_loop_source), solo_pool, cache, env
        )
        elapsed = time.monotonic() - start
    assert result.status == "timeout"
    assert result.error_code == "exec_timeout"
    assert elapsed < task.timeout_s + 10  # killed promptly, not left to run to completion


def test_block_network_denies_socket_connect():
    block_network()
    import socket

    with pytest.raises(NetworkAccessDisabled):
        socket.socket().connect(("example.com", 80))
