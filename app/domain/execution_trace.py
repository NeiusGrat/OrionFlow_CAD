from typing import List, Optional
from pydantic import BaseModel


class TraceEvent(BaseModel):
    stage: str                  # e.g. "sketch_compile", "feature_extrude"
    target: Optional[str]       # sketch id or feature id
    status: str                 # "success" | "failure"
    message: Optional[str] = None


class ExecutionTrace(BaseModel):
    success: bool
    events: List[TraceEvent]
    retryable: bool = False
