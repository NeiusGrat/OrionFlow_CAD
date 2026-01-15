from pydantic import BaseModel
from typing import Optional, Dict

from app.domain.feature_graph_v3 import FeatureGraphV3
from app.domain.execution_trace import ExecutionTrace


class DatasetSample(BaseModel):
    """Single logged generation sample for active learning.

    Stores the V3 feature graph (design-intent IR) along with the
    execution trace and metadata needed for offline analysis.
    """

    prompt: str
    decomposed_intent: Dict
    feature_graph: FeatureGraphV3
    execution_trace: ExecutionTrace
    success: bool
    backend: str
    timestamp: str
