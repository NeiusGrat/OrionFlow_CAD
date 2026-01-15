"""
FeatureGraph V2 Schema - Semantic Intermediate Representation

Extends V1 with semantic topology references for complex edge/face selection.

Key additions:
- SelectorType: STRING, SEMANTIC, FILTER_CHAIN, REFERENCE
- GeometricFilter: Filter definitions for topology selection
- SemanticSelector: Advanced selector with filters or references
- FeatureV2: Features with topology_refs field
- FeatureGraphV2: Version 2.0 schema

Backward compatible with V1 through version detection.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union, Literal, Any
from enum import Enum


# -------------------------
# Selector Types
# -------------------------

class SelectorType(str, Enum):
    """Type of topology selector for edge/face selection"""
    STRING = "string"           # Simple Build123d selector: ">Z", "|X"
    SEMANTIC = "semantic"       # Object-based semantic selector with filters
    FILTER_CHAIN = "filter_chain"  # Multiple filters combined (AND logic)
    REFERENCE = "reference"     # Reference to previous feature's topology


class GeometricFilterType(str, Enum):
    """Types of geometric filters for topology selection"""
    PARALLEL_TO_AXIS = "parallel_to_axis"
    PERPENDICULAR_TO_AXIS = "perpendicular_to_axis"
    ON_FACE = "on_face"
    LENGTH_RANGE = "length_range"
    RADIUS_RANGE = "radius_range"
    DISTANCE_FROM_POINT = "distance_from_point"
    DIRECTION = "direction"  # Edge pointing in direction


class GeometricFilter(BaseModel):
    """
    Single geometric filter for topology selection.
    
    Used to narrow down edge/face candidates based on geometric properties.
    """
    type: GeometricFilterType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True


class SemanticSelector(BaseModel):
    """
    Advanced topology selector with multiple selection strategies.
    
    Supports:
    - String selectors (Build123d syntax: ">Z", "|X")
    - Semantic filters (parallel_to_axis, on_face, etc.)
    - References to previous features (for VERSION 0.4)
    """
    selector_type: SelectorType
    
    # For STRING type - direct Build123d selector
    string_selector: Optional[str] = None  # e.g., ">Z", "<X", "|Y"
    
    # For SEMANTIC / FILTER_CHAIN type - list of filters (AND logic)
    filters: Optional[List[GeometricFilter]] = None
    
    # For REFERENCE type - reference to previous feature's topology
    feature_ref: Optional[str] = None  # Feature ID to reference
    topology_type: Optional[Literal["edge", "face", "vertex"]] = None
    
    # Metadata for debugging and LLM context
    description: Optional[str] = None
    
    # Phase 2: Explicit entity targeting (4-tier resolution)
    entity_ids: Optional[List[str]] = Field(
        None, 
        description="Explicit entity UUIDs to target (Tier 1: highest priority)"
    )
    created_by_feature: Optional[str] = Field(
        None,
        description="Select entities created by this feature ID (Tier 2)"
    )
    semantic_roles: Optional[List[str]] = Field(
        None,
        description="Select entities with these semantic role tags (Tier 3)"
    )  # Human-readable: "top edges parallel to X"
    
    class Config:
        use_enum_values = True
    
    def is_simple_string(self) -> bool:
        """Check if this is a simple string selector."""
        return self.selector_type == SelectorType.STRING and self.string_selector is not None


# -------------------------
# Sketch Layer (same as V1)
# -------------------------

class SketchPrimitiveV2(BaseModel):
    """Sketch primitive with parameters - same as V1"""
    id: str
    type: Literal["line", "circle", "arc", "rectangle", "point"]
    params: Dict[str, Any] = Field(default_factory=dict)
    construction: bool = False


class SketchConstraintV2(BaseModel):
    """Sketch constraint - same as V1"""
    type: Literal[
        "coincident", "parallel", "perpendicular",
        "horizontal", "vertical", "distance",
        "radius", "angle", "symmetric"
    ]
    entities: List[str]
    value: Optional[Union[str, float]] = None


class SketchGraphV2(BaseModel):
    """2D Sketch definition - compatible with V1"""
    id: str
    plane: Literal["XY", "YZ", "XZ"] = "XY"
    primitives: List[SketchPrimitiveV2] = Field(default_factory=list)
    constraints: List[SketchConstraintV2] = Field(default_factory=list)


# -------------------------
# Feature Layer (V2)
# -------------------------

class FeatureV2(BaseModel):
    """
    Feature with semantic topology references.
    
    Extends V1 Feature with:
    - topology_refs: Named semantic selectors for edges, faces, etc.
    - dependencies: Explicit feature dependencies
    """
    id: str
    type: Literal["extrude", "fillet", "chamfer", "revolve", "shell", "pattern"]
    
    # Parameters for the feature operation
    params: Dict[str, Any] = Field(default_factory=dict)
    
    # Optional sketch reference (for sketch-based features)
    sketch: Optional[str] = None
    
    # NEW: Semantic topology references
    # Keys are reference names (e.g., "edges", "faces", "target_edges")
    # Values are SemanticSelectors defining how to select topology
    topology_refs: Optional[Dict[str, SemanticSelector]] = None
    
    # Explicit feature dependencies
    dependencies: List[str] = Field(default_factory=list)


# -------------------------
# FeatureGraph V2 (Top-Level)
# -------------------------

class FeatureGraphV2(BaseModel):
    """
    Version 2 Feature Graph with semantic selectors.
    
    Key differences from V1:
    - version: "2.0" (for detection)
    - features use FeatureV2 with topology_refs
    - context: Optional design context for LLM conversation
    """
    version: Literal["2.0"] = "2.0"
    units: Literal["mm", "cm", "inch"] = "mm"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Parameters table (same as V1)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    
    # Sketches (compatible with V1)
    sketches: List[SketchGraphV2] = Field(default_factory=list)
    
    # Features with semantic selectors
    features: List[FeatureV2] = Field(default_factory=list)
    
    # NEW: Design context for conversational editing
    context: Optional[Dict[str, Any]] = None


# -------------------------
# Conversion Utilities
# -------------------------

def string_selector(selector: str, description: str = None) -> SemanticSelector:
    """Create a simple string selector."""
    return SemanticSelector(
        selector_type=SelectorType.STRING,
        string_selector=selector,
        description=description
    )


def semantic_selector(
    *filters: GeometricFilter,
    description: str = None
) -> SemanticSelector:
    """Create a semantic selector from filters."""
    return SemanticSelector(
        selector_type=SelectorType.SEMANTIC,
        filters=list(filters),
        description=description
    )


def parallel_to_axis(axis: str) -> GeometricFilter:
    """Filter: edges/faces parallel to axis (X, Y, Z)."""
    return GeometricFilter(
        type=GeometricFilterType.PARALLEL_TO_AXIS,
        parameters={"axis": axis}
    )


def on_face(face_selector: str) -> GeometricFilter:
    """Filter: edges on a specific face."""
    return GeometricFilter(
        type=GeometricFilterType.ON_FACE,
        parameters={"face_selector": face_selector}
    )


def length_range(min_length: float = None, max_length: float = None) -> GeometricFilter:
    """Filter: edges within length range."""
    params = {}
    if min_length is not None:
        params["min"] = min_length
    if max_length is not None:
        params["max"] = max_length
    return GeometricFilter(
        type=GeometricFilterType.LENGTH_RANGE,
        parameters=params
    )


# -------------------------
# Example V2 Feature Graph
# -------------------------

EXAMPLE_V2_GRAPH = {
    "version": "2.0",
    "units": "mm",
    "metadata": {"intent": "Box with filleted top edges"},
    "parameters": {
        "width": {"type": "float", "value": 30},
        "depth": {"type": "float", "value": 20},
        "height": {"type": "float", "value": 15},
        "fillet_radius": {"type": "float", "value": 2}
    },
    "sketches": [
        {
            "id": "sketch_1",
            "plane": "XY",
            "primitives": [
                {
                    "id": "rect_1",
                    "type": "rectangle",
                    "params": {"width": "$width", "height": "$depth"}
                }
            ],
            "constraints": []
        }
    ],
    "features": [
        {
            "id": "extrude_1",
            "type": "extrude",
            "sketch": "sketch_1",
            "params": {"depth": "$height"}
        },
        {
            "id": "fillet_1",
            "type": "fillet",
            "params": {"radius": "$fillet_radius"},
            "topology_refs": {
                "edges": {
                    "selector_type": "semantic",
                    "filters": [
                        {"type": "parallel_to_axis", "parameters": {"axis": "X"}},
                        {"type": "on_face", "parameters": {"face_selector": ">Z"}}
                    ],
                    "description": "top edges parallel to X axis"
                }
            },
            "dependencies": ["extrude_1"]
        }
    ]
}
