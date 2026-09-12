"""OF-TR-002 §5. The only shared vocabulary in orion-harness.

Frozen after M0: a change here must update every consumer in the same PR
(AGENTS.md). Every model is immutable and rejects unknown fields so a typo
in a task YAML or a verifier result fails loudly instead of silently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True, extra="forbid")


# ---------- identity ----------


class EnvDigest(BaseModel):
    """Pinned environment. Recorded in every result (R7)."""

    model_config = _FROZEN

    harness_version: str
    geometry_image: str | None = None
    physics_image: str | None = None
    solver_versions: dict[str, str] = Field(default_factory=dict)


# ---------- task ----------

Split = Literal["dev", "frozen", "held_out"]
Pillar = Literal["query", "modify", "reconstruct", "design"]
CheckKind = Literal["gate", "metric"]
SubmissionKind = Literal["ofl", "featuregraph", "build123d", "step"]


class ReferenceSpec(BaseModel):
    """Ground-truth artifact for optional reference-based scoring (Tier ref)."""

    model_config = _FROZEN

    kind: Literal["step", "geom_hash"]
    path: str | None = None
    geom_hash: str | None = None


class CheckSpec(BaseModel):
    model_config = _FROZEN

    name: str
    verifier: str  # registry key, e.g. "tier1.rebuild_deterministic"
    kind: CheckKind
    params: dict = Field(default_factory=dict)
    target: dict | None = None  # {"min": 2.0} / {"max": 0.25} / {"equals": 4}
    weight: float = 0.0  # metrics only; gates ignore it


class TaskSpec(BaseModel):
    model_config = _FROZEN

    task_id: str
    family: str
    pillar: Pillar
    split: Split
    difficulty: Literal[1, 2, 3, 4, 5]
    prompt: str
    assets: list[str] = Field(default_factory=list)
    spec: dict = Field(default_factory=dict)
    checks: list[CheckSpec]
    reference: ReferenceSpec | None = None
    timeout_s: int = 300
    provenance: str
    tags: list[str] = Field(default_factory=list)


# ---------- submission ----------


class Usage(BaseModel):
    model_config = _FROZEN

    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class Submission(BaseModel):
    model_config = _FROZEN

    task_id: str
    kind: SubmissionKind
    payload: str  # source text or a path; never executed in-process (R5)
    model_id: str = "oracle"
    sample_index: int = 0
    seed: int | None = None
    raw_completion: str = ""
    usage: Usage = Field(default_factory=Usage)


# ---------- results ----------


class GateResult(BaseModel):
    model_config = _FROZEN

    name: str
    passed: bool
    reason: str | None = None  # short, machine-greppable
    evidence: dict = Field(default_factory=dict)


class SolverProvenance(BaseModel):
    model_config = _FROZEN

    name: str
    version: str
    wall_s: float | None = None


class Metric(BaseModel):
    model_config = _FROZEN

    name: str
    value: float
    unit: str
    target: dict | None = None
    slack: float | None = None  # normalized: -g_i, negative = violated
    provenance: list[SolverProvenance] = Field(default_factory=list)


Status = Literal["scored", "invalid", "error", "timeout", "skipped"]

# Closed failure taxonomy (§6.3). Keep in sync with runner/errors.py.
ErrorCode = Literal[
    "model_api_error",
    "model_refusal",
    "parse_error",
    "exec_timeout",
    "exec_crash",
    "gate_failed",
    "solver_infra_error",
    "solver_result_implausible",
    "harness_bug",
]


class Result(BaseModel):
    model_config = _FROZEN

    task_id: str
    submission_hash: str
    env: EnvDigest
    status: Status
    error_code: ErrorCode | None = None  # set iff status in {"error","timeout"}
    gates: list[GateResult] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    score: float | None = None  # None unless status == "scored" (never 0.0 as sentinel)
    geom_hash: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    wall_s: float = 0.0
    cached: bool = False
