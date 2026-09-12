"""Glue: TaskSpec + Submission -> cached, classified Result.

This is the one path every caller (CLI `run`/`verify`, and eventually the
RL environment, §12) goes through. Scoring itself (§9.1's weighted
metrics) happens inside the worker (runner/jobs.py, score/rubric.py); this
module only classifies the *shape* of what came back (ok / gate_failed /
crash / timeout / infra error) into a Result -- never a sentinel 0.0 for
"did not run" (R3).
"""

from __future__ import annotations

import hashlib
import time

from ..contracts import EnvDigest, GateResult, Metric, Result, Submission, TaskSpec
from ..registry import verifier_version
from .cache import ResultCache, cache_key
from .errors import CODE_STATUS
from .pool import WorkerPool


def _submission_hash(submission: Submission) -> str:
    return hashlib.sha256(submission.payload.encode("utf-8")).hexdigest()


def evaluate_submission(
    task: TaskSpec,
    submission: Submission,
    pool: WorkerPool,
    cache: ResultCache,
    env: EnvDigest,
) -> Result:
    verifier_versions = {c.verifier: verifier_version(c.verifier) for c in task.checks}
    key = cache_key(task, submission.payload, verifier_versions, env)

    cached = cache.get(key)
    if cached is not None:
        return cached

    sub_hash = _submission_hash(submission)
    checks_payload = [c.model_dump(mode="json") for c in task.checks]
    start = time.monotonic()
    outcome = pool.submit(
        kind=submission.kind,
        payload=submission.payload,
        checks=checks_payload,
        timeout_s=task.timeout_s,
    )
    wall_s = time.monotonic() - start

    if outcome["status"] == "timeout":
        result = Result(
            task_id=task.task_id,
            submission_hash=sub_hash,
            env=env,
            status="timeout",
            error_code="exec_timeout",
            wall_s=wall_s,
        )
    elif outcome["status"] == "crash":
        result = Result(
            task_id=task.task_id,
            submission_hash=sub_hash,
            env=env,
            status="invalid",
            error_code="exec_crash",
            wall_s=wall_s,
        )
    elif outcome["status"] == "outcome":
        code = outcome["code"]
        result = Result(
            task_id=task.task_id,
            submission_hash=sub_hash,
            env=env,
            status=CODE_STATUS[code],
            error_code=code,
            wall_s=wall_s,
        )
    else:  # "ok"
        payload = outcome["result"]
        gates = [GateResult.model_validate(g) for g in payload["gates"]]
        metrics = [Metric.model_validate(m) for m in payload["metrics"]]
        all_gates_pass = all(g.passed for g in gates)
        result = Result(
            task_id=task.task_id,
            submission_hash=sub_hash,
            env=env,
            status="scored",
            error_code=None if all_gates_pass else "gate_failed",
            gates=gates,
            metrics=metrics,
            score=payload["score"],
            geom_hash=payload["geom_hash"],
            wall_s=wall_s,
        )

    cache.put(key, result)
    return result
