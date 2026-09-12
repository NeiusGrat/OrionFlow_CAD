"""`orion-harness tasks lint` (§10). Checks what can be checked statically,
without running anything: families are known (so the cluster key used by
score/stats.py is never a typo of one), every check's verifier actually
exists in the registry, and every metric-kind check's weights sum to a
positive number (so score/rubric.py's ValueError at run time was always
going to be a lint failure, not a surprise mid-eval).

Does NOT check training-corpus contamination (§8.4) -- this repo has no
training-corpus membership index to check against, and claiming this
function does that check would be exactly the kind of quiet overclaim
OF-TR-002 argues against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..registry import UnknownVerifierError, get_verifier
from .families import is_known_family
from .loader import load_task_file


@dataclass
class LintIssue:
    task_id: str
    path: str
    message: str


@dataclass
class LintReport:
    n_tasks: int
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def lint_task_file(path: Path) -> list[LintIssue]:
    issues: list[LintIssue] = []
    try:
        task = load_task_file(path)
    except Exception as e:
        return [LintIssue(task_id=path.stem, path=str(path), message=f"failed to load: {e}")]

    if not is_known_family(task.family):
        issues.append(
            LintIssue(
                task_id=task.task_id,
                path=str(path),
                message=f"unknown family {task.family!r} (not in tasks/families.py FAMILIES)",
            )
        )

    for check in task.checks:
        try:
            get_verifier(check.verifier)
        except UnknownVerifierError as e:
            issues.append(
                LintIssue(task_id=task.task_id, path=str(path), message=f"check {check.name!r}: {e}")
            )

    metric_checks = [c for c in task.checks if c.kind == "metric"]
    if metric_checks:
        total_weight = sum(c.weight for c in metric_checks)
        if total_weight <= 0:
            issues.append(
                LintIssue(
                    task_id=task.task_id,
                    path=str(path),
                    message=f"metric checks have non-positive total weight ({total_weight})",
                )
            )

    if not task.checks:
        issues.append(
            LintIssue(task_id=task.task_id, path=str(path), message="task declares zero checks")
        )

    return issues


def lint_tasks_root(tasks_root: Path, splits: tuple[str, ...] = ("dev", "frozen")) -> LintReport:
    issues: list[LintIssue] = []
    n_tasks = 0
    for split in splits:
        split_dir = tasks_root / split
        if not split_dir.is_dir():
            continue
        for p in sorted(split_dir.glob("*.yaml")):
            n_tasks += 1
            issues.extend(lint_task_file(p))
    return LintReport(n_tasks=n_tasks, issues=issues)
