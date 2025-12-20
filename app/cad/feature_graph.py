from typing import List, Dict, Any
from pydantic import BaseModel

class Feature(BaseModel):
    id: str
    type: str
    params: Dict[str, Any]

class FeatureGraph(BaseModel):
    part_type: str
    base_plane: str = "XY"
    features: List[Feature]
