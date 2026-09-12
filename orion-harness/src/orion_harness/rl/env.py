"""§12 RL interface. Same environment object, second consumer: the CLI's
`evaluate_submission` is the only scoring path here too (R1) -- there is
no separate "RL reward" implementation to drift out of sync with the eval.

**Session scope:** `fidelity="fast"` is implemented as *skipping* T3
physics checks, not as running an analytic prefilter or surrogate model --
no surrogate was built in this pass (that is real modeling work, not
wiring). This is stated here rather than silently claimed: a caller
relying on "fast" to mean "approximately physics-checked" would be wrong
today. `fidelity="full"` runs every declared check including tier3.static,
which requires a solver run this environment cannot itself produce (see
verify/tier3_physics.py's module docstring) -- a caller must supply
solver-observable params via the task/submission for tier3 checks to do
anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import __version__
from ..contracts import EnvDigest, Result, Submission, TaskSpec
from ..runner.cache import ResultCache
from ..runner.evaluate import evaluate_submission
from ..runner.pool import WorkerPool
from ..tasks.loader import load_split
from .rubric import Rubric, RewardBreakdown, default_rubric

FidelityLevel = str  # "fast" | "full"


def _strip_physics_checks(task: TaskSpec) -> TaskSpec:
    kept = [c for c in task.checks if not c.verifier.startswith("tier3.")]
    if len(kept) == len(task.checks):
        return task
    return task.model_copy(update={"checks": kept})


@dataclass
class RolloutResult:
    task_id: str
    result: Result
    reward: RewardBreakdown


class OrionCADEnv:
    def __init__(
        self,
        dataset: list[TaskSpec],
        rubric: Rubric,
        pool: WorkerPool,
        cache: ResultCache,
        env_digest: EnvDigest,
        fidelity: FidelityLevel = "fast",
    ):
        if fidelity not in ("fast", "full"):
            raise ValueError(f"fidelity must be 'fast' or 'full', got {fidelity!r}")
        self.dataset = dataset
        self._tasks_by_id = {t.task_id: t for t in dataset}
        self.rubric = rubric
        self.pool = pool
        self.cache = cache
        self.env_digest = env_digest
        self.fidelity = fidelity

    def rollout(self, task_id: str, submission: Submission) -> RolloutResult:
        if task_id not in self._tasks_by_id:
            raise KeyError(f"task_id {task_id!r} not in this environment's dataset")
        task = self._tasks_by_id[task_id]
        if self.fidelity == "fast":
            task = _strip_physics_checks(task)

        result = evaluate_submission(task, submission, self.pool, self.cache, self.env_digest)
        reward = self.rubric.score(
            result=result, raw_completion=submission.raw_completion or submission.payload
        )
        return RolloutResult(task_id=task_id, result=result, reward=reward)

    def close(self) -> None:
        self.pool.shutdown()

    def __enter__(self) -> "OrionCADEnv":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def load_environment(
    tasks_root: str,
    split: str = "dev",
    families: list[str] | None = None,
    fidelity: FidelityLevel = "fast",
    n_workers: int = 2,
    cache_dir: str = ".orion_harness_rl_cache",
) -> OrionCADEnv:
    tasks = load_split(tasks_root, split)
    if families:
        tasks = [t for t in tasks if t.family in families]
    if not tasks:
        raise ValueError(f"no tasks found for split={split!r} families={families!r}")

    rubric = default_rubric()
    pool = WorkerPool(n_workers=n_workers)
    cache = ResultCache(cache_dir)
    env_digest = EnvDigest(harness_version=__version__)
    return OrionCADEnv(
        dataset=tasks, rubric=rubric, pool=pool, cache=cache, env_digest=env_digest, fidelity=fidelity
    )
