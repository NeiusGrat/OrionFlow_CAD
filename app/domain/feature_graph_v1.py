from typing import List, Dict, Optional, Literal, Union
from pydantic import BaseModel, Field


# -------------------------
# Parameters
# -------------------------

class Parameter(BaseModel):
    type: Literal["float", "int", "bool"]
    value: Union[float, int, bool]
    min: Optional[float] = None
    max: Optional[float] = None


# -------------------------
# Sketch Layer (2D)
# -------------------------

class SketchPrimitive(BaseModel):
    id: str
    type: Literal[
        "line",
        "circle",
        "arc",
        "rectangle",
        "point"
    ]
    params: Dict[str, Union[str, float]]
    construction: bool = False


class SketchConstraint(BaseModel):
    type: Literal[
        "coincident",
        "parallel",
        "perpendicular",
        "horizontal",
        "vertical",
        "distance",
        "radius",
        "angle",
        "symmetric"
    ]
    entities: List[str]
    value: Optional[Union[str, float]] = None


class SketchGraph(BaseModel):
    id: str
    plane: Literal["XY", "YZ", "XZ"]
    primitives: List[SketchPrimitive]
    constraints: List[SketchConstraint]


# -------------------------
# Feature Layer (3D)
# -------------------------

class Feature(BaseModel):
    id: str
    type: Literal[
        "extrude",
        "revolve",
        "fillet",
        "chamfer"
    ]
    sketch: Optional[str] = None
    targets: Optional[List[str]] = None
    params: Dict[str, Union[str, float]]


# -------------------------
# FeatureGraph (Top-Level)
# -------------------------

class FeatureGraphV1(BaseModel):
    schema_version: Literal["1.0"]
    units: Literal["mm", "cm", "inch"]
    metadata: Dict[str, str]

    parameters: Dict[str, Parameter]
    sketches: List[SketchGraph]
    features: List[Feature]
