from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    stage: str                  # e.g. "sketch_compile", "feature_extrude"
    target: Optional[str]       # sketch id or feature id
    status: str                 # "success" | "failure"
    message: Optional[str] = None


class ExecutionTrace(BaseModel):
    """
    Structured trace of compilation execution.
    For Phase 2+ retry logic with clear failure context.
    """
    success: bool
    events: List[TraceEvent]
    retryable: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)  # Phase 2: entity registry, etc.
