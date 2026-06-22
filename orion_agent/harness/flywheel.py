"""Trajectory flywheel — curate logged sessions into training-ready splits.

The runtime logs every turn (schema v1.0). This module filters those rows into:
  * SFT targets — successful, grounded/verified turns rendered as
    instruction/response(/tool-trace) examples,
  * GRPO rows — turns that already carry a reward signal (the verification block
    becomes the scalar reward), kept regardless of success.

This is the bridge from the runtime to fine-tuning; it does not train anything,
it just produces clean splits.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from orion_agent.shared.config import get_config
from orion_agent.shared.trajectory import Trajectory
from orion_agent.harness.trajectory_logger import TrajectoryLogger


@dataclass
class ExportStats:
    total: int = 0
    sft: int = 0
    grpo: int = 0
    rejected: int = 0


def _reward(traj: Trajectory) -> float:
    """Scalar reward in [0,1] from the verification block (GRPO signal)."""
    if traj.reward.score is not None:
        return float(traj.reward.score)
    vb = traj.validation
    flags = [vb.executed, vb.edit_survived, vb.intent_consistent,
             vb.no_unintended_change, vb.grounded]
    present = [f for f in flags if f is not None]
    if not present:
        return 0.0
    return sum(1 for f in present if f) / len(present)


def _is_sft_quality(traj: Trajectory) -> bool:
    if traj.error:
        return False
    if not traj.final_answer.strip():
        return False
    if traj.pillar == "query":
        # grounded answers only
        return traj.validation.grounded is not False
    # mutation pillars: require verification to have passed
    return traj.validation.passed()


def _to_sft_row(traj: Trajectory) -> dict:
    tool_trace = []
    for m in traj.messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                tool_trace.append({"tool": tc.name, "arguments": tc.arguments,
                                   "result": tc.result_preview})
    return {
        "pillar": traj.pillar,
        "model_tier": traj.model_tier,
        "instruction": traj.user_request,
        "response": traj.final_answer,
        "tool_trace": tool_trace,
        "trajectory_id": traj.trajectory_id,
    }


class FlywheelExporter:
    def __init__(self, logger: Optional[TrajectoryLogger] = None, out_dir: Optional[str] = None):
        cfg = get_config()
        self.logger = logger or TrajectoryLogger()
        self.out_dir = out_dir or os.path.join(cfg.repo_root, cfg.trajectory_dir, "export")
        os.makedirs(self.out_dir, exist_ok=True)

    def export(self, pillar: Optional[str] = None) -> ExportStats:
        stats = ExportStats()
        sft_path = os.path.join(self.out_dir, "sft.jsonl")
        grpo_path = os.path.join(self.out_dir, "grpo.jsonl")
        with open(sft_path, "w", encoding="utf-8") as sft_fh, \
                open(grpo_path, "w", encoding="utf-8") as grpo_fh:
            for traj in self.logger.read_all(pillar=pillar):
                stats.total += 1
                # GRPO row: every turn with any reward signal.
                reward = _reward(traj)
                grpo_fh.write(json.dumps({
                    "trajectory_id": traj.trajectory_id,
                    "pillar": traj.pillar,
                    "instruction": traj.user_request,
                    "response": traj.final_answer,
                    "reward": reward,
                    "components": {
                        "executed": traj.validation.executed,
                        "edit_survived": traj.validation.edit_survived,
                        "intent_consistent": traj.validation.intent_consistent,
                        "no_unintended_change": traj.validation.no_unintended_change,
                        "grounded": traj.validation.grounded,
                    },
                }, ensure_ascii=False) + "\n")
                stats.grpo += 1
                # SFT row: quality-filtered only.
                if _is_sft_quality(traj):
                    sft_fh.write(json.dumps(_to_sft_row(traj), ensure_ascii=False) + "\n")
                    stats.sft += 1
                else:
                    stats.rejected += 1
        return stats


def main() -> int:
    stats = FlywheelExporter().export()
    print(f"[flywheel] total={stats.total} sft={stats.sft} "  # noqa: T201
          f"grpo={stats.grpo} rejected={stats.rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
