"""Locate and register the OrionFlow_CAD repo root on sys.path.

orion-harness deliberately reuses `orionflow_ofl` and `app.compilers.*`
rather than reimplementing CAD logic (R1) -- both live one level above
this package's own root, in the parent OrionFlow_CAD repo:

    OrionFLow_CAD/                 <- _REPO_ROOT
    |-- orionflow_ofl/
    |-- app/
    `-- orion-harness/             <- this package's root
        `-- src/orion_harness/_repo_root.py   <- this file

Worker processes (runner/pool.py) are spawned as separate Python
interpreters and do not automatically inherit path setup a caller did in
its own process (e.g. pytest's conftest.py) -- each worker must register
this for itself, hence a function to call at worker startup rather than a
one-shot script.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def ensure_repo_root_on_path() -> None:
    repo_root_str = str(_REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
