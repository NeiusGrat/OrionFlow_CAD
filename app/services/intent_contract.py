from pydantic import BaseModel
from typing import List


class DecomposedIntent(BaseModel):
    sketch_intent: List[str]
    constraint_intent: List[str]
    feature_intent: List[str]
    unsupported_intent: List[str]
