"""Trajectory schema v1.0.

Every session, in every pillar, is logged as a structured trajectory. The
runtime therefore doubles as the data-collection engine for later supervised
and RL fine-tuning. This same model is consumed by the logger, the eval
harness (scoring), and the training-export step (Phase 7 flywheel).

Stdlib dataclasses only (no pydantic) so it imports everywhere. ``validate``
performs lightweight structural checks; ``to_dict`` produces a JSON-ready row.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

SCHEMA_VERSION = "1.0"


# --------------------------------------------------------------------------- #
# Sub-blocks
# --------------------------------------------------------------------------- #


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result_preview: str = ""          # token-bounded preview of the result
    ok: bool = True
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class Message:
    role: str                         # system | user | assistant | tool
    content: str = ""
    thinking: str = ""                # reasoning channel (k2v2 think)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None        # tool name for role == 'tool'
    timestamp: float = field(default_factory=time.time)


@dataclass
class Artifact:
    """A file produced during the turn (STEP/STL/GLB) or a render PNG."""

    kind: str                         # step | stl | glb | render | drawing
    path: str
    label: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationBlock:
    """Outcome of the verification policy for the turn.

    Query: grounding checks. Modify: the four-check verification loop.
    Reconstruct: render-vs-drawing divergence.
    """

    executed: Optional[bool] = None           # code ran / recompute ok
    edit_survived: Optional[bool] = None       # downstream features still build
    intent_consistent: Optional[bool] = None   # spec-consistency (reference-free)
    no_unintended_change: Optional[bool] = None
    grounded: Optional[bool] = None            # every claim cites a tool result
    divergence: Optional[float] = None         # reconstruct render delta
    checks: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def passed(self) -> bool:
        flags = [
            self.executed,
            self.edit_survived,
            self.intent_consistent,
            self.no_unintended_change,
            self.grounded,
        ]
        present = [f for f in flags if f is not None]
        return bool(present) and all(present)


@dataclass
class RewardBlock:
    """Scoring used for SFT curation and as the GRPO reward signal."""

    success: Optional[bool] = None
    score: Optional[float] = None     # scalar reward in [0, 1]
    components: dict[str, float] = field(default_factory=dict)
    source: str = "runtime"           # runtime | eval


@dataclass
class Provenance:
    model: str = ""
    provider: str = ""
    harness_version: str = ""
    contract_version: str = ""
    freecad_version: str = ""
    host: str = "local"


# --------------------------------------------------------------------------- #
# Top-level row
# --------------------------------------------------------------------------- #


@dataclass
class Trajectory:
    # identity
    trajectory_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    schema_version: str = SCHEMA_VERSION
    created_at: float = field(default_factory=time.time)

    # specification
    pillar: str = "query"             # query | modify | reconstruct | generate
    model_tier: str = "unknown"       # §4 tier of the open model
    user_request: str = ""
    document_name: str = ""
    spec: dict = field(default_factory=dict)   # generate: parsed EngineeringSpec

    # trace
    messages: list[Message] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)

    # outcome
    final_answer: str = ""
    validation: ValidationBlock = field(default_factory=ValidationBlock)
    reward: RewardBlock = field(default_factory=RewardBlock)
    provenance: Provenance = field(default_factory=Provenance)

    # bookkeeping
    duration_ms: float = 0.0
    step_count: int = 0
    error: str = ""

    # ------------------------------------------------------------------ #
    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts.append(artifact)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        """Return a list of structural problems (empty == valid)."""
        problems: list[str] = []
        if self.schema_version != SCHEMA_VERSION:
            problems.append(f"schema_version mismatch: {self.schema_version}")
        if self.pillar not in {"query", "modify", "reconstruct", "generate"}:
            problems.append(f"unknown pillar: {self.pillar}")
        if not self.user_request:
            problems.append("user_request is empty")
        for i, m in enumerate(self.messages):
            if m.role not in {"system", "user", "assistant", "tool"}:
                problems.append(f"message[{i}] bad role: {m.role}")
        return problems

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Trajectory":
        msgs = [
            Message(
                role=m.get("role", "user"),
                content=m.get("content", ""),
                thinking=m.get("thinking", ""),
                tool_calls=[ToolCall(**tc) for tc in m.get("tool_calls", [])],
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                timestamp=m.get("timestamp", time.time()),
            )
            for m in d.get("messages", [])
        ]
        arts = [Artifact(**a) for a in d.get("artifacts", [])]
        traj = Trajectory(
            trajectory_id=d.get("trajectory_id", uuid.uuid4().hex),
            session_id=d.get("session_id", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            created_at=d.get("created_at", time.time()),
            pillar=d.get("pillar", "query"),
            model_tier=d.get("model_tier", "unknown"),
            user_request=d.get("user_request", ""),
            document_name=d.get("document_name", ""),
            spec=d.get("spec", {}) or {},
            messages=msgs,
            artifacts=arts,
            final_answer=d.get("final_answer", ""),
            validation=ValidationBlock(**d.get("validation", {})),
            reward=RewardBlock(**d.get("reward", {})),
            provenance=Provenance(**d.get("provenance", {})),
            duration_ms=d.get("duration_ms", 0.0),
            step_count=d.get("step_count", 0),
            error=d.get("error", ""),
        )
        return traj
