"""§13.1: every oracle must score 1.0. If one doesn't, investigate the task
before trusting any model number measured against it -- do not lower the bar
to make the number look better (AGENTS.md: "Do not improve a score by
relaxing a gate").
"""

import pytest

from orion_harness.contracts import EnvDigest, Submission
from orion_harness.runner.cache import ResultCache
from orion_harness.runner.evaluate import evaluate_submission
from orion_harness.runner.pool import WorkerPool
from orion_harness.tasks.loader import load_split

from conftest import ORACLES_ROOT, TASKS_ROOT

_EXT_TO_KIND = ((".ofl.py", "ofl"), (".b123d.py", "build123d"), (".json", "featuregraph"))


def _env():
    return EnvDigest(harness_version="0.1.0")


@pytest.fixture(scope="module")
def pool():
    with WorkerPool(n_workers=2) as p:
        yield p


def _oracle_submission(task_id: str) -> Submission:
    for ext, kind in _EXT_TO_KIND:
        path = ORACLES_ROOT / f"{task_id}{ext}"
        if path.exists():
            return Submission(
                task_id=task_id, kind=kind, payload=path.read_text(encoding="utf-8")
            )
    raise AssertionError(f"no oracle for {task_id} under {ORACLES_ROOT}")


def _all_tasks():
    return load_split(TASKS_ROOT, "dev") + load_split(TASKS_ROOT, "frozen")


def test_dev_split_has_at_least_twenty_tasks():
    tasks = load_split(TASKS_ROOT, "dev")
    assert len(tasks) >= 20, "M1 acceptance (§14 M1): 20 dev tasks must run end-to-end"


@pytest.mark.parametrize("task_id", [t.task_id for t in _all_tasks()])
def test_oracle_scores_one(task_id, pool):
    tasks = {t.task_id: t for t in _all_tasks()}
    task = tasks[task_id]
    submission = _oracle_submission(task_id)
    cache = ResultCache(".pytest_orion_harness_cache")
    result = evaluate_submission(task, submission, pool, cache, _env())

    assert result.status == "scored", (task_id, result.status, result.error_code, result.gates)
    assert result.score == 1.0, (task_id, [g for g in result.gates if not g.passed])
