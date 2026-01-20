"""
Canonical Feature Graph IR (Execution IR) - OrionFlow's Compiled Representation

==============================================================================
ARCHITECTURE PRINCIPLE: FeatureGraph = LLVM IR for CAD
==============================================================================

This module defines the EXECUTION-ONLY intermediate representation for CAD.
It is the contract between the planning layer and the compiler.

WHAT FEATUREGRAPH IR IS:
- A mechanical, deterministic specification of geometry operations
- Fully resolved parameters (no ambiguity)
- Ordered operation sequence with explicit dependencies
- Kernel-agnostic (portable to Build123d, Onshape, CadQuery, etc.)

WHAT FEATUREGRAPH IR IS NOT:
- NOT a place for reasoning or intent
- NOT for design rationale or manufacturing preferences
- NOT for symmetry, functional requirements, or material choices
- NOT for user-facing descriptions or explanations

PIPELINE POSITION:
    User Prompt
         |
         v
    DesignIntent (what is it? high-level reasoning)
         |
         v
    ConstructionPlan (how to build it? step-by-step reasoning)
         |
         v
    FeatureGraphIR (exact ops - THIS FILE) <-- Intelligence Boundary
         |
         v
    Compiler (Build123d, Onshape, etc.)
         |
         v
    Geometry (STEP, STL, GLB)

RULES FOR LLM:
1. LLM is NEVER allowed to invent geometry logic inside FeatureGraphIR
2. All reasoning MUST happen in ConstructionPlan (upstream)
3. FeatureGraphIR must be deterministically reproducible
4. Any ambiguity = compilation failure (fail fast)

Version: 1.0-IR (Execution IR - FROZEN)
"""
from typing import List, Dict, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
import hashlib
import json


# =============================================================================
# IR Constants (Frozen - Do Not Extend Without Versioning)
# =============================================================================

class IRVersion(str, Enum):
    """Supported IR versions. New features require new version."""
    V1_0 = "1.0-IR"


class SketchPlane(str, Enum):
    """Supported sketch planes."""
    XY = "XY"
    YZ = "YZ"
    XZ = "XZ"


class PrimitiveType(str, Enum):
    """Allowed sketch primitive types."""
    LINE = "line"
    CIRCLE = "circle"
    ARC = "arc"
    RECTANGLE = "rectangle"
    POINT = "point"


class ConstraintType(str, Enum):
    """Allowed sketch constraint types."""
    COINCIDENT = "coincident"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    EQUAL = "equal"
    DISTANCE = "distance"
    RADIUS = "radius"
    ANGLE = "angle"
    SYMMETRIC = "symmetric"
    TANGENT = "tangent"
    CONCENTRIC = "concentric"


class FeatureType(str, Enum):
    """Allowed 3D feature types."""
    EXTRUDE = "extrude"
    CUT = "cut"
    FILLET = "fillet"
    CHAMFER = "chamfer"
    REVOLVE = "revolve"
    LOFT = "loft"
    PATTERN = "pattern"


class UnitSystem(str, Enum):
    """Supported unit systems."""
    MM = "mm"
    INCH = "inch"


# =============================================================================
# Parameter System (Resolved Values Only)
# =============================================================================

class ResolvedParameter(BaseModel):
    """
    A fully resolved parameter value.

    IR RULE: Parameters MUST be resolved to concrete numeric values.
    No symbolic references, no expressions, no ambiguity.
    """
    value: float = Field(..., description="Concrete numeric value (resolved)")

    # Optional bounds for validation (compiler can check)
    min_value: Optional[float] = Field(None, description="Minimum valid value")
    max_value: Optional[float] = Field(None, description="Maximum valid value")

    @field_validator('value')
    @classmethod
    def validate_finite(cls, v):
        """Ensure value is finite and not NaN."""
        import math
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"Parameter value must be finite, got {v}")
        return v

    @model_validator(mode='after')
    def validate_bounds(self):
        """Ensure value is within bounds if specified."""
        if self.min_value is not None and self.value < self.min_value:
            raise ValueError(f"Value {self.value} below minimum {self.min_value}")
        if self.max_value is not None and self.value > self.max_value:
            raise ValueError(f"Value {self.value} above maximum {self.max_value}")
        return self


# =============================================================================
# Sketch Layer (2D Primitives)
# =============================================================================

class SketchPrimitiveIR(BaseModel):
    """
    Atomic 2D geometric entity with RESOLVED parameters.

    IR RULE: All parameter references must be resolved to floats.
    The compiler receives concrete values, not "$param_name" strings.
    """
    id: str = Field(..., description="Unique entity ID within the sketch")
    type: PrimitiveType = Field(..., description="Primitive type from allowlist")

    # RESOLVED parameters - no "$param" references allowed
    params: Dict[str, float] = Field(
        ...,
        description="Geometric parameters - ALL values must be resolved floats"
    )

    # Construction geometry flag (not part of final profile)
    construction: bool = Field(False, description="True if construction geometry")

    @field_validator('params')
    @classmethod
    def validate_resolved_params(cls, v):
        """Ensure all parameter values are resolved (no string references)."""
        for key, val in v.items():
            if isinstance(val, str):
                raise ValueError(
                    f"IR violation: Parameter '{key}' has unresolved string value '{val}'. "
                    f"All parameters must be resolved to floats before IR generation."
                )
            if not isinstance(val, (int, float)):
                raise ValueError(
                    f"IR violation: Parameter '{key}' must be numeric, got {type(val)}"
                )
        return {k: float(v) for k, v in v.items()}


class SketchConstraintIR(BaseModel):
    """
    Geometric constraint with RESOLVED values.
    """
    type: ConstraintType = Field(..., description="Constraint type from allowlist")
    entities: List[str] = Field(..., description="IDs of constrained entities")

    # RESOLVED value (if applicable)
    value: Optional[float] = Field(None, description="Constraint value (resolved)")

    @field_validator('value')
    @classmethod
    def validate_resolved_value(cls, v):
        """Ensure constraint value is resolved if present."""
        if v is not None and isinstance(v, str):
            raise ValueError(
                f"IR violation: Constraint value must be resolved float, got string '{v}'"
            )
        return v


class SketchIR(BaseModel):
    """
    2D Sketch with RESOLVED geometry.
    """
    id: str = Field(..., description="Unique sketch ID")
    plane: SketchPlane = Field(SketchPlane.XY, description="Construction plane")
    primitives: List[SketchPrimitiveIR] = Field(..., description="2D primitives")
    constraints: List[SketchConstraintIR] = Field(
        default_factory=list,
        description="Sketch constraints"
    )

    @field_validator('primitives')
    @classmethod
    def validate_non_empty(cls, v):
        """Sketch must have at least one primitive."""
        if not v:
            raise ValueError("IR violation: Sketch must have at least one primitive")
        return v


# =============================================================================
# Feature Layer (3D Operations)
# =============================================================================

class FeatureIR(BaseModel):
    """
    3D Operation with RESOLVED parameters and explicit dependencies.

    IR RULE: Features form a DAG. Compiler executes in dependency order.
    """
    id: str = Field(..., description="Unique feature ID")
    type: FeatureType = Field(..., description="Feature type from allowlist")

    # Sketch reference (for sketch-based operations)
    sketch: Optional[str] = Field(None, description="ID of source sketch")

    # RESOLVED parameters - no "$param" references
    params: Dict[str, float] = Field(
        ...,
        description="Operation parameters - ALL values must be resolved floats"
    )

    # Explicit dependency chain (for incremental rebuild)
    depends_on: List[str] = Field(
        default_factory=list,
        description="IDs of parent features (must execute before this)"
    )

    # Cache key for incremental compilation (STEP 3 preparation)
    _param_hash: Optional[str] = None

    @field_validator('params')
    @classmethod
    def validate_resolved_params(cls, v):
        """Ensure all parameter values are resolved."""
        for key, val in v.items():
            if isinstance(val, str):
                raise ValueError(
                    f"IR violation: Feature param '{key}' has unresolved string '{val}'"
                )
        return {k: float(v) for k, v in v.items()}

    def compute_param_hash(self) -> str:
        """Compute hash of parameters for caching (STEP 3 preparation)."""
        param_str = json.dumps(self.params, sort_keys=True)
        return hashlib.sha256(param_str.encode()).hexdigest()[:16]


# =============================================================================
# FeatureGraphIR (Root - Execution IR)
# =============================================================================

class FeatureGraphIR(BaseModel):
    """
    Canonical Feature Graph IR - EXECUTION ONLY

    This is the FROZEN contract between planning and compilation.

    RULES:
    1. All parameters are RESOLVED (no "$param" references)
    2. All dependencies are EXPLICIT
    3. No reasoning, intent, or rationale allowed
    4. Must be deterministically compilable

    FORBIDDEN FIELDS (must live upstream in ConstructionPlan/DesignIntent):
    - symmetry
    - manufacturing_intent
    - functional_requirements
    - design_rationale
    - material_preference
    - open_questions
    - assumptions

    VERSION POLICY:
    - This schema is FROZEN at 1.0-IR
    - New features require new version number
    - Breaking changes require migration path
    """
    # Version tag (frozen)
    version: Literal["1.0-IR"] = Field(
        "1.0-IR",
        description="IR version - FROZEN, do not change"
    )

    # Unit system
    units: UnitSystem = Field(UnitSystem.MM, description="Unit system for all values")

    # RESOLVED parameter table
    parameters: Dict[str, ResolvedParameter] = Field(
        default_factory=dict,
        description="Global parameters with RESOLVED values"
    )

    # 2D Sketches
    sketches: List[SketchIR] = Field(
        default_factory=list,
        description="2D sketch definitions"
    )

    # 3D Features (operation history)
    features: List[FeatureIR] = Field(
        ...,
        description="Ordered 3D operations"
    )

    # Minimal metadata (for tracking only, not reasoning)
    metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="Tracking metadata only (job_id, timestamp, source_plan_id)"
    )

    @field_validator('features')
    @classmethod
    def validate_non_empty(cls, v):
        """IR must have at least one feature."""
        if not v:
            raise ValueError("IR violation: Must have at least one feature")
        return v

    @model_validator(mode='after')
    def validate_dependencies(self):
        """Validate feature dependency DAG."""
        feature_ids = {f.id for f in self.features}

        for feature in self.features:
            for dep in feature.depends_on:
                if dep not in feature_ids:
                    raise ValueError(
                        f"IR violation: Feature '{feature.id}' depends on "
                        f"unknown feature '{dep}'"
                    )

        # Check for cycles (simple DFS)
        visited = set()
        rec_stack = set()

        def has_cycle(fid: str) -> bool:
            visited.add(fid)
            rec_stack.add(fid)

            feature = next((f for f in self.features if f.id == fid), None)
            if feature:
                for dep in feature.depends_on:
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True

            rec_stack.remove(fid)
            return False

        for f in self.features:
            if f.id not in visited:
                if has_cycle(f.id):
                    raise ValueError(
                        f"IR violation: Dependency cycle detected involving '{f.id}'"
                    )

        return self

    @model_validator(mode='after')
    def validate_sketch_references(self):
        """Validate all sketch references exist."""
        sketch_ids = {s.id for s in self.sketches}

        for feature in self.features:
            if feature.sketch and feature.sketch not in sketch_ids:
                raise ValueError(
                    f"IR violation: Feature '{feature.id}' references "
                    f"unknown sketch '{feature.sketch}'"
                )

        return self

    def get_resolved_param(self, name: str) -> Optional[float]:
        """Get a resolved parameter value by name."""
        param = self.parameters.get(name)
        return param.value if param else None

    def topological_sort_features(self) -> List[FeatureIR]:
        """Return features in dependency order (for compilation)."""
        if not self.features:
            return []

        # Build adjacency list
        id_to_feature = {f.id: f for f in self.features}
        in_degree = {f.id: 0 for f in self.features}
        graph = {f.id: [] for f in self.features}

        for f in self.features:
            for dep in f.depends_on:
                if dep in graph:
                    graph[dep].append(f.id)
                    in_degree[f.id] += 1

        # Kahn's algorithm
        queue = [fid for fid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(id_to_feature[current])

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def compute_graph_hash(self) -> str:
        """Compute hash of entire IR for caching."""
        ir_dict = self.model_dump()
        ir_str = json.dumps(ir_dict, sort_keys=True)
        return hashlib.sha256(ir_str.encode()).hexdigest()[:32]


# =============================================================================
# IR Builder (Resolves parameters from FeatureGraph + ConstructionPlan)
# =============================================================================

class IRBuilder:
    """
    Builds FeatureGraphIR from upstream planning artifacts.

    Resolves all parameter references and validates the result.
    This is the INTELLIGENCE BOUNDARY - after this, no reasoning allowed.
    """

    @staticmethod
    def resolve_param_value(
        raw_value: Union[str, float, int],
        param_table: Dict[str, float]
    ) -> float:
        """
        Resolve a parameter reference to a concrete value.

        Args:
            raw_value: Either a float or "$param_name" reference
            param_table: Resolved parameter values

        Returns:
            Resolved float value

        Raises:
            ValueError: If reference cannot be resolved
        """
        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        if isinstance(raw_value, str):
            if raw_value.startswith("$"):
                param_name = raw_value[1:]
                if param_name not in param_table:
                    raise ValueError(
                        f"Cannot resolve parameter reference '{raw_value}': "
                        f"'{param_name}' not in parameter table"
                    )
                return param_table[param_name]
            else:
                # Try parsing as float
                try:
                    return float(raw_value)
                except ValueError:
                    raise ValueError(
                        f"Cannot resolve value '{raw_value}': "
                        f"not a valid float or parameter reference"
                    )

        raise ValueError(f"Unexpected value type: {type(raw_value)}")

    @classmethod
    def from_feature_graph_v1(
        cls,
        fg: Any,
        source_plan_id: Optional[str] = None
    ) -> FeatureGraphIR:
        """
        Build IR from FeatureGraphV1.

        Resolves all "$param" references to concrete values.

        Args:
            fg: FeatureGraphV1 object
            source_plan_id: Optional ID of source ConstructionPlan

        Returns:
            Fully resolved FeatureGraphIR
        """
        # Build resolved parameter table
        param_table: Dict[str, float] = {}
        resolved_params: Dict[str, ResolvedParameter] = {}

        for name, param in fg.parameters.items():
            if hasattr(param, 'value'):
                value = float(param.value)
            else:
                value = float(param)

            param_table[name] = value
            resolved_params[name] = ResolvedParameter(value=value)

        # Resolve sketches
        resolved_sketches: List[SketchIR] = []
        for sketch in fg.sketches:
            resolved_primitives = []

            primitives = getattr(sketch, 'primitives', []) or getattr(sketch, 'entities', [])
            for prim in primitives:
                resolved_prim_params = {}
                for key, val in prim.params.items():
                    resolved_prim_params[key] = cls.resolve_param_value(val, param_table)

                resolved_primitives.append(SketchPrimitiveIR(
                    id=prim.id,
                    type=prim.type,
                    params=resolved_prim_params,
                    construction=getattr(prim, 'construction', False)
                ))

            resolved_constraints = []
            for constr in sketch.constraints:
                resolved_value = None
                if constr.value is not None:
                    resolved_value = cls.resolve_param_value(constr.value, param_table)

                resolved_constraints.append(SketchConstraintIR(
                    type=constr.type,
                    entities=list(constr.entities),
                    value=resolved_value
                ))

            resolved_sketches.append(SketchIR(
                id=sketch.id,
                plane=sketch.plane,
                primitives=resolved_primitives,
                constraints=resolved_constraints
            ))

        # Resolve features
        resolved_features: List[FeatureIR] = []
        for feature in fg.features:
            resolved_feature_params = {}
            for key, val in feature.params.items():
                resolved_feature_params[key] = cls.resolve_param_value(val, param_table)

            depends_on = getattr(feature, 'depends_on', []) or []

            resolved_features.append(FeatureIR(
                id=feature.id,
                type=feature.type,
                sketch=feature.sketch,
                params=resolved_feature_params,
                depends_on=list(depends_on)
            ))

        # Build metadata
        metadata = {
            "ir_version": "1.0-IR",
            "source": "feature_graph_v1"
        }
        if source_plan_id:
            metadata["source_plan_id"] = source_plan_id

        return FeatureGraphIR(
            version="1.0-IR",
            units=fg.units if hasattr(fg, 'units') else "mm",
            parameters=resolved_params,
            sketches=resolved_sketches,
            features=resolved_features,
            metadata=metadata
        )
