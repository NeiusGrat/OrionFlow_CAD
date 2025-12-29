from pydantic import BaseModel
from typing import Literal, Optional

class Intent(BaseModel):
    part_type: Literal[
        "box",
        "cylinder",
        "shaft",
        "gear"
    ]
    shape_hint: Optional[str] = None
    confidence: float = 1.0  # Confidence score for intent parsing robustness
