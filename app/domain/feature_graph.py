"""
Canonical Feature Graph (CFG) v1 - LLM Output Schema

==============================================================================
IMPORTANT: This is the LLM OUTPUT schema, NOT the compiler input.
==============================================================================

This schema defines what the LLM produces. It may contain:
- Parameter REFERENCES ("$param_name") - not resolved yet
- Minimal metadata for tracking

PIPELINE POSITION:
    LLM → FeatureGraph (this file) → IRBuilder → FeatureGraphIR → Compiler

For the compiled Execution IR (what the compiler sees), use:
    app.domain.feature_graph_ir.FeatureGraphIR

This schema will be DEPRECATED in favor of FeatureGraphIR once the
full pipeline migration is complete.

Version: v1 (LEGACY - prefer FeatureGraphIR for new code)
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

    # -------------------------------------------------------------------------
    # IR Conversion Methods
    # -------------------------------------------------------------------------

    def to_ir(self, source_plan_id: Optional[str] = None):
        """
        Convert this FeatureGraph to FeatureGraphIR (Execution IR).

        This resolves all "$param" references and validates the result.
        Use this before passing to the compiler.

        Args:
            source_plan_id: Optional ID of source ConstructionPlan for tracing

        Returns:
            FeatureGraphIR with all parameters resolved

        Raises:
            ValueError: If parameter resolution fails
        """
        from app.domain.feature_graph_ir import IRBuilder
        return IRBuilder.from_feature_graph_v1(self, source_plan_id)

    def validate_for_ir(self) -> List[str]:
        """
        Validate this FeatureGraph against IR rules.

        Returns list of violations (empty if valid).
        Call this to check if the graph can be converted to IR.
        """
        violations = []

        # Check for forbidden metadata fields (should be in ConstructionPlan)
        forbidden_metadata = [
            "symmetry", "manufacturing_intent", "functional_requirements",
            "design_rationale", "material_preference", "assumptions",
            "open_questions", "manufacturing_constraints"
        ]

        if self.metadata:
            for key in forbidden_metadata:
                if key in self.metadata:
                    violations.append(
                        f"Metadata contains forbidden field '{key}' - "
                        f"this belongs in ConstructionPlan, not FeatureGraph"
                    )

        # Check for undefined parameter references
        param_names = set(self.parameters.keys())

        for sketch in self.sketches:
            for entity in sketch.entities:
                for key, val in entity.params.items():
                    if isinstance(val, str) and val.startswith("$"):
                        ref_name = val[1:]
                        if ref_name not in param_names:
                            violations.append(
                                f"Sketch entity '{entity.id}' references "
                                f"undefined parameter '{ref_name}'"
                            )

        for feature in self.features:
            for key, val in feature.params.items():
                if isinstance(val, str) and val.startswith("$"):
                    ref_name = val[1:]
                    if ref_name not in param_names:
                        violations.append(
                            f"Feature '{feature.id}' references "
                            f"undefined parameter '{ref_name}'"
                        )

        return violations

    def strip_forbidden_fields(self) -> "FeatureGraph":
        """
        Return a copy with forbidden metadata fields removed.

        Use this to clean LLM output before conversion to IR.
        """
        forbidden = {
            "symmetry", "manufacturing_intent", "functional_requirements",
            "design_rationale", "material_preference", "assumptions",
            "open_questions", "manufacturing_constraints"
        }

        clean_metadata = {
            k: v for k, v in (self.metadata or {}).items()
            if k not in forbidden
        }

        return FeatureGraph(
            version=self.version,
            units=self.units,
            parameters=self.parameters.copy(),
            sketches=self.sketches.copy(),
            features=self.features.copy(),
            metadata=clean_metadata
        )
