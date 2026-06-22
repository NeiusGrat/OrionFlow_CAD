"""Trajectory logger — the data-collection sink that doubles the runtime as the
training-data engine.

Writes one JSON line per turn (schema v1.0). Files are partitioned by pillar and
day so curation/export (Phase 7) can filter cheaply. Logging never raises into
the agent loop: a logging failure must not break a user's session.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from orion_agent.shared.config import get_config
from orion_agent.shared.trajectory import Trajectory


class TrajectoryLogger:
    def __init__(self, root: Optional[str] = None):
        cfg = get_config()
        self.root = root or os.path.join(cfg.repo_root, cfg.trajectory_dir)
        os.makedirs(self.root, exist_ok=True)

    def log(self, traj: Trajectory) -> Optional[str]:
        try:
            problems = traj.validate()
            if problems:
                traj.error = (traj.error + " | schema: " + "; ".join(problems)).strip(" |")
            day = time.strftime("%Y%m%d", time.localtime(traj.created_at))
            path = os.path.join(self.root, f"{traj.pillar}_{day}.jsonl")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(traj.to_dict(), ensure_ascii=False) + "\n")
            return path
        except Exception:  # noqa: BLE001 - logging must never break the session
            return None

    def read_all(self, pillar: Optional[str] = None) -> list[Trajectory]:
        rows: list[Trajectory] = []
        for fname in os.listdir(self.root):
            if not fname.endswith(".jsonl"):
                continue
            if pillar and not fname.startswith(pillar + "_"):
                continue
            with open(os.path.join(self.root, fname), "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(Trajectory.from_dict(json.loads(line)))
        return rows
