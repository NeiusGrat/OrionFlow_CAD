from pydantic import BaseModel
from typing import Optional, Dict
from app.domain.feature_graph_v1 import FeatureGraphV1
from app.domain.execution_trace import ExecutionTrace


class DatasetSample(BaseModel):
    prompt: str
    decomposed_intent: Dict
    feature_graph: FeatureGraphV1
    execution_trace: ExecutionTrace
    success: bool
    backend: str
    timestamp: str
