"""
Canonical Feature Graph (CFG) v1 - OrionFlow's Core Data Model

A declarative, order-aware, parametric representation of CAD models.
Designed for portability (Build123d, Onshape, SketchGraphs).

Version: v1 (FINAL)
"""
from typing import List, Dict, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, validator

# -----------------------------------------------------------------------------
# 1. Sketch Entities & Constraints
# -----------------------------------------------------------------------------

class SketchEntity(BaseModel):
    """
    Atomic 2D geometric entity (line, circle, arc, rectangle).
    Parameters can reference global parameters using '$name' syntax.
    """
    id: str = Field(..., description="Unique entity ID within the sketch")
    type: Literal["line", "circle", "arc", "rectangle"]
    params: Dict[str, Union[str, float]] = Field(
        ..., 
        description="Geometric parameters (e.g., {'radius': '$r'} or {'width': 10.0})"
    )

class SketchConstraint(BaseModel):
    """
    Geometric constraint applied to sketch entities.
    Compatible with SketchGraphs and Onshape solvers.
    """
    type: Literal[
        "coincident",
        "horizontal",
        "vertical",
        "parallel",
        "perpendicular",
        "equal",
        "distance",
        "symmetry",
        "tangent",
        "concentric"
    ]
    entities: List[str] = Field(..., description="IDs of entities affected by this constraint")
    value: Optional[Union[str, float]] = Field(None, description="Constraint value (if applicable, e.g. distance)")

class Sketch(BaseModel):
    """
    2D Sketch defined on a plane. Container for entities and constraints.
    """
    id: str = Field(..., description="Unique sketch ID")
    plane: Literal["XY", "YZ", "XZ"] = Field("XY", description="Construction plane")
    entities: List[SketchEntity]
    constraints: List[SketchConstraint] = Field(default_factory=list)

# -----------------------------------------------------------------------------
# 2. 3D Features (History Tree)
# -----------------------------------------------------------------------------

class Feature(BaseModel):
    """
    3D Operation applied to sketches or existing geometry.
    """
    id: str = Field(..., description="Unique feature ID")
    type: Literal[
        "extrude",
        "cut",
        "fillet",
        "chamfer",
        "pattern",
        "revolve",
        "loft"
    ]
    sketch: Optional[str] = Field(None, description="ID of the sketch to operate on (if applicable)")
    params: Dict[str, Union[str, float]] = Field(
        ..., 
        description="Operation parameters (e.g. {'depth': '$thickness'})"
    )
    depends_on: List[str] = Field(default_factory=list, description="IDs of parent features (for history)")

# -----------------------------------------------------------------------------
# 3. Canonical Feature Graph (Root)
# -----------------------------------------------------------------------------

class FeatureGraph(BaseModel):
    """
    Canonical Feature Graph v1 (FINAL)
    
    The single source of truth for all CAD operations.
    - Declarative: describes WHAT, not HOW
    - Parametric: uses named variables
    - Kernel-agnostic: portable to Any CAD engine
    """
    version: Literal["v1"] = "v1"
    units: Literal["mm", "inch"] = "mm"
    
    # 3️⃣ Parameters (Single source of truth)
    parameters: Dict[str, float] = Field(
        ..., 
        description="Global design parameters (name -> float value)"
    )
    
    # 4️⃣ Sketches (2D)
    sketches: List[Sketch] = Field(
        default_factory=list,
        description="List of 2D sketches used by features"
    )
    
    # 5️⃣ Features (3D History)
    features: List[Feature] = Field(
        ..., 
        description="Ordered list of 3D operations"
    )
    
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    @validator('parameters')
    def validate_parameters(cls, v):
        """Ensure parameters are valid numbers."""
        for name, val in v.items():
            if not isinstance(val, (int, float)):
                raise ValueError(f"Parameter '{name}' must be a number, got {type(val)}")
        return v
