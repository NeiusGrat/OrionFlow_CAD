"""The argument every registered verifier receives.

A verifier should never know how its shape was obtained (OFL vs
FeatureGraph, one build vs two) -- that is the job dispatcher's problem
(runner/jobs.py). This keeps a verifier's signature identical whether it
runs against an `ofl` or a `featuregraph` submission, which is what lets
the same registry entry serve both kinds (R1).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VerifyContext:
    kind: str
    payload: object
    shape: object | None = None
    shape_rebuild: object | None = None
    geom_hash: str | None = None
    geom_hash_rebuild: str | None = None
    params: dict = field(default_factory=dict)
