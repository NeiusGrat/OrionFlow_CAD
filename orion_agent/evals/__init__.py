"""Eval harness.

Per-pillar suites scored from real (or known-synthetic) geometry, never model
self-report. The same machinery is the GRPO reward environment later: a Modify
case that scores edit-survival + intent-match is exactly a reward function.
"""

from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel
from orion_agent.evals.harness import EvalHarness, EvalCase, EvalResult

__all__ = [
    "SyntheticBridge",
    "SyntheticModel",
    "EvalHarness",
    "EvalCase",
    "EvalResult",
]
