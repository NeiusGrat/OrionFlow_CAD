"""YAML -> TaskSpec, with split enforcement (R8).

`held_out` may only be loaded with `ORION_RELEASE_GATE=1` set, and doing so
is meant to happen in release CI only -- see §8.1. This module is the one
place that checks it; nothing downstream may load `held_out` tasks another
way. `held_out` task files are additionally encrypted at rest
(held_out_crypto.py) -- release CI needs both the gate env var and the
decryption key.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from ..contracts import TaskSpec
from .held_out_crypto import decrypt

RELEASE_GATE_ENV = "ORION_RELEASE_GATE"


class SplitAccessDenied(PermissionError):
    pass


def _check_split_matches_directory(path: Path, task: TaskSpec) -> None:
    # Only enforce agreement when the parent directory is itself one of the
    # split names -- a single ad hoc task file elsewhere is not a hygiene bug.
    if path.parent.name in {"dev", "frozen", "held_out"} and path.parent.name != task.split:
        raise SplitAccessDenied(
            f"{path}: declares split={task.split!r} but lives under "
            f"{path.parent.name!r}/ -- split and directory must agree"
        )


def load_task_file(path: str | Path) -> TaskSpec:
    """Loads a plain (non-encrypted) task YAML. For `held_out`, use
    `load_split` -- held_out tasks are encrypted at rest and are not meant
    to be read one file at a time outside release CI (§8.1)."""

    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    task = TaskSpec.model_validate(data)

    if task.split == "held_out" and os.environ.get(RELEASE_GATE_ENV) != "1":
        raise SplitAccessDenied(
            f"{path}: held_out task {task.task_id!r} requires "
            f"{RELEASE_GATE_ENV}=1 (release CI only, §8.1)"
        )

    _check_split_matches_directory(path, task)
    return task


def _load_held_out(tasks_root: Path) -> list[TaskSpec]:
    if os.environ.get(RELEASE_GATE_ENV) != "1":
        raise SplitAccessDenied(f"loading split='held_out' requires {RELEASE_GATE_ENV}=1 (§8.1)")

    split_dir = tasks_root / "held_out"
    if not split_dir.is_dir():
        return []

    tasks = []
    for path in sorted(split_dir.glob("*.yaml.enc")):
        plaintext = decrypt(path.read_bytes())
        task = TaskSpec.model_validate(yaml.safe_load(plaintext))
        if task.split != "held_out":
            raise SplitAccessDenied(
                f"{path}: decrypted content declares split={task.split!r}, expected 'held_out'"
            )
        tasks.append(task)
    return tasks


def load_split(tasks_root: str | Path, split: str) -> list[TaskSpec]:
    tasks_root = Path(tasks_root)
    if split == "held_out":
        return _load_held_out(tasks_root)

    split_dir = tasks_root / split
    if not split_dir.is_dir():
        return []
    return [load_task_file(p) for p in sorted(split_dir.glob("*.yaml"))]
