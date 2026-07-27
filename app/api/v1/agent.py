"""Physical AI agent endpoint — one call from prompt to simulation-ready part.

POST /api/v1/agent/design returns the full harness bundle: reasoning trace,
sourced standard parts, OFL code, geometry stats, DFM analysis, and URDF/SDF.
"""

from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Agent"])

# Lazy init so the server starts without an LLM key configured.
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        from orion_physical_ai import PhysicalAIAgent

        _agent = PhysicalAIAgent()
    return _agent


class AgentDesignRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=4000)
    material: Optional[str] = Field(
        default=None, description="Knowledge-base material key, e.g. aluminum_6061_t6"
    )
    max_repairs: int = Field(default=2, ge=0, le=4)
    use_llm_reasoning: bool = True


class AgentDesignResponse(BaseModel):
    success: bool
    intent: str = "generate"
    reasoning: dict[str, Any] = {}
    sourced_parts: list[dict[str, Any]] = []
    ofl_code: str = ""
    files: dict[str, Any] = {}
    parameters: list[dict[str, Any]] = []
    stats: Optional[dict[str, Any]] = None
    analysis: Optional[dict[str, Any]] = None
    mass_properties: Optional[dict[str, Any]] = None
    urdf: Optional[str] = None
    sdf: Optional[str] = None
    repair_attempts: int = 0
    trace: list[dict[str, Any]] = []
    error: Optional[str] = None
    generation_time_ms: float = 0
    #: Explicit record of what was checked and what it proved. Present on every
    #: response, including failures — a refusal is the useful answer when the
    #: alternative is geometry the caller cannot tell is wrong.
    verification: dict[str, Any] = {}


# Sync handler on purpose: LLM HTTP + sandbox subprocess + trimesh are
# blocking; a sync def runs in the threadpool instead of freezing the loop.
@router.post("/design", response_model=AgentDesignResponse)
def agent_design(request: AgentDesignRequest):
    """Run the full Physical AI harness on a design brief."""
    agent = get_agent()
    agent.use_llm_reasoning = request.use_llm_reasoning
    bundle = agent.design(
        request.prompt,
        material=request.material,
        max_repairs=request.max_repairs,
    )
    bundle.pop("prompt", None)
    # Derived, never authored by the model: the report is built from the build
    # log and the measured geometry, so a model cannot talk its way to a green
    # tick. See orion_physical_ai/verify.py for what each check does and does
    # not claim.
    from orion_physical_ai import verify

    bundle["verification"] = verify.from_bundle(bundle)
    return AgentDesignResponse(**bundle)
