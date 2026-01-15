"""FeatureGraph V3 - Design-intent CAD IR.

Encodes four layers explicitly:
1. Parameters (named, shareable across the model)
2. Sketch geometry (2D primitives)
3. Constraints (sketch-level and global)
4. Feature history with explicit dependencies

V3 is implemented as a thin layer over the existing V2 sketch/feature
primitives so that compilers and validation logic can be reused.

Primary usage in Phase 1:
- Hold design intent (parameters, constraints, dependencies).
- Provide a stable, constraint-aware projection to FeatureGraphV1 for
  the existing Build123d compiler.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union, Literal

from pydantic import BaseModel, Field

from app.domain.feature_graph_v1 import (
    FeatureGraphV1,
    Parameter as ParameterV1,
    SketchGraph as SketchGraphV1,
    SketchPrimitive as SketchPrimitiveV1,
    SketchConstraint as SketchConstraintV1,
    Feature as FeatureV1,
)
from app.domain.feature_graph_v2 import (
    SketchPrimitiveV2,
    SketchConstraintV2,
    SketchGraphV2,
    FeatureV2,
)


class ConstraintType(str, Enum):
    """Types of high-level constraints supported in V3.

    This is intentionally small for Phase 1 and focused on the
    operations the compiler can reasonably enforce:
    - EQUAL: keep a set of parameters equal.
    - DIMENSION: fix a parameter (or set of parameters) to a value.
    - PARALLEL: geometric relation between topology entities (stored
      but not yet solved in Phase 1).
    """

    EQUAL = "equal"
    DIMENSION = "dimension"
    PARALLEL = "parallel"


class Constraint(BaseModel):
    """Top-level design constraint.

    Examples:
    - Geometric parallelism:
      {"id": "c1", "type": "parallel", "entities": ["edge_12", "edge_18"]}

    - Parameter equality:
      {"id": "c2", "type": "equal", "parameters": ["hole_d1", "hole_d2"]}

    - Dimension on a parameter:
      {"id": "c3", "type": "dimension", "parameters": ["height"], "value": 20.0}
    """

    id: str
    type: ConstraintType

    # Topology references (e.g. edge/face handles or selectors)
    entities: List[str] = Field(default_factory=list)

    # Parameter names participating in this constraint
    parameters: List[str] = Field(default_factory=list)

    # Optional numeric or symbolic value (for dimensions)
    value: Optional[Union[float, str]] = None

    # Optional expression for future symbolic constraints
    expression: Optional[str] = None


class FeatureGraphV3(BaseModel):
    """FeatureGraph V3 - single source of truth for CAD design intent.

    This schema is intentionally close to FeatureGraphV2 at the
    sketch/feature level, but adds:
    - Explicit version tag ("3.0").
    - Parameter table compatible with V1/V2 usage.
    - Top-level constraint list.
    - Utility methods to project into FeatureGraphV1 for compilation.
    """

    version: Literal["3.0"] = "3.0"
    units: Literal["mm", "cm", "inch"] = "mm"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Parameters table; values are either numeric/bool or dicts with
    # at least a "value" key (as in V1/V2).
    parameters: Dict[str, Any] = Field(default_factory=dict)

    # Reuse V2 sketch primitives & constraints for 2D geometry
    sketches: List[SketchGraphV2] = Field(default_factory=list)

    # Reuse V2 feature representation with explicit dependencies
    features: List[FeatureV2] = Field(default_factory=list)

    # New: global constraint layer
    constraints: List[Constraint] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience: parameter helpers
    # ------------------------------------------------------------------

    def _get_param_entry(self, name: str) -> Optional[Any]:
        """Return the raw parameter entry for a given name, if present."""

        return self.parameters.get(name)

    def _get_param_value(self, name: str) -> Optional[Union[float, int, bool]]:
        """Extract a numeric/bool value from a parameter entry if possible."""

        entry = self._get_param_entry(name)
        if entry is None:
            return None

        if isinstance(entry, (int, float, bool)):
            return entry

        if isinstance(entry, dict):
            if "value" in entry and isinstance(entry["value"], (int, float, bool)):
                return entry["value"]

        return None

    def _set_param_value(self, name: str, value: Union[float, int, bool]) -> None:
        """Set or update a parameter entry's value in a backward-compatible way."""

        entry = self.parameters.get(name)
        if isinstance(entry, dict):
            # Preserve any extra metadata if present
            entry.setdefault("type", "float")
            entry["value"] = value
            self.parameters[name] = entry
        else:
            # Store as minimal dict so downstream tools can still
            # treat this like a V2-style parameter table.
            self.parameters[name] = {"type": "float", "value": value}

    # ------------------------------------------------------------------
    # Constraint application & dependency handling
    # ------------------------------------------------------------------

    def apply_parameter_constraints(self) -> None:
        """Apply simple parameter-level constraints in-place.

        Phase 1 scope:
        - EQUAL: unify all listed parameters to the first one's value
          (if that value is known).
        - DIMENSION: set the listed parameter(s) to the constraint
          value when numeric.

        Geometric (PARALLEL) constraints are stored but *not* solved
        here; they are intended for future compiler support.
        """

        # First, equality constraints between parameters
        for c in self.constraints:
            if c.type == ConstraintType.EQUAL and c.parameters:
                base_name = c.parameters[0]
                base_val = self._get_param_value(base_name)
                if base_val is None:
                    # Nothing to propagate
                    continue

                for other_name in c.parameters[1:]:
                    self._set_param_value(other_name, base_val)

        # Second, explicit dimension constraints on parameters
        for c in self.constraints:
            if (
                c.type == ConstraintType.DIMENSION
                and c.parameters
                and isinstance(c.value, (int, float))
            ):
                dim_val = float(c.value)
                for pname in c.parameters:
                    self._set_param_value(pname, dim_val)

    def topologically_sorted_features(self) -> List[FeatureV2]:
        """Return features sorted by their dependency graph.

        If a cycle or invalid dependency is detected, this falls back
        to the original order to avoid breaking compilation.
        """

        if not self.features:
            return []

        # Build adjacency and indegree maps
        id_to_feature: Dict[str, FeatureV2] = {f.id: f for f in self.features}
        indegree: Dict[str, int] = {f.id: 0 for f in self.features}
        graph: Dict[str, List[str]] = {f.id: [] for f in self.features}

        # Populate from dependencies
        for f in self.features:
            deps = getattr(f, "dependencies", []) or []
            for dep in deps:
                if dep not in indegree:
                    # Unknown dependency; ignore but keep original order
                    continue
                indegree[f.id] += 1
                graph[dep].append(f.id)

        # Kahn's algorithm with deterministic ordering based on the
        # original feature list
        original_ids = [f.id for f in self.features]
        queue: List[str] = [fid for fid in original_ids if indegree[fid] == 0]
        result_ids: List[str] = []

        while queue:
            # Maintain original ordering by popping from the front
            current = queue.pop(0)
            result_ids.append(current)

            for nxt in graph[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        if len(result_ids) != len(self.features):
            # Cycle or invalid graph; fall back to original ordering
            return self.features

        return [id_to_feature[fid] for fid in result_ids]

    # ------------------------------------------------------------------
    # Conversions to/from FeatureGraphV1
    # ------------------------------------------------------------------

    @classmethod
    def from_v1(cls, graph_v1: FeatureGraphV1) -> "FeatureGraphV3":
        """Lift a FeatureGraphV1 into V3.

        This keeps the geometry and parameters but does *not* attempt
        to infer new constraints or dependencies beyond what V1
        already encodes.
        """

        # Parameters: convert Parameter objects to plain dicts
        params_v3: Dict[str, Any] = {}
        for name, param in graph_v1.parameters.items():
            # model_dump gives {"type": ..., "value": ..., "min": ..., "max": ...}
            params_v3[name] = param.model_dump()

        # Sketches: map V1 SketchGraph → V2-style SketchGraphV2
        sketches_v3: List[SketchGraphV2] = []
        for s in graph_v1.sketches:
            primitives_v2 = [
                SketchPrimitiveV2(**p.model_dump()) for p in s.primitives
            ]
            constraints_v2 = [
                SketchConstraintV2(**c.model_dump()) for c in s.constraints
            ]
            sketches_v3.append(
                SketchGraphV2(
                    id=s.id,
                    plane=s.plane,
                    primitives=primitives_v2,
                    constraints=constraints_v2,
                )
            )

        # Features: map V1 Feature → V2 FeatureV2 with empty dependencies
        features_v3: List[FeatureV2] = []
        for f in graph_v1.features:
            features_v3.append(
                FeatureV2(
                    id=f.id,
                    type=f.type,
                    sketch=f.sketch,
                    params=dict(f.params),
                    topology_refs=None,
                    dependencies=[],
                )
            )

        return cls(
            units=graph_v1.units,
            metadata=dict(graph_v1.metadata),
            parameters=params_v3,
            sketches=sketches_v3,
            features=features_v3,
            constraints=[],
        )

    def to_v1(self) -> FeatureGraphV1:
        """Project this V3 graph down to FeatureGraphV1 for compilation.

        This applies parameter-level constraints and uses the
        dependency graph to derive a stable feature ordering.
        """

        # Normalize parameters using constraints
        self.apply_parameter_constraints()

        # Derive a stable feature ordering
        ordered_features = self.topologically_sorted_features()

        # Parameters: convert back to ParameterV1 objects
        params_v1: Dict[str, ParameterV1] = {}
        for name, raw in self.parameters.items():
            if isinstance(raw, dict):
                value = raw.get("value", 0.0)
                ptype = raw.get("type", "float")
                params_v1[name] = ParameterV1(
                    type=ptype, value=value, min=raw.get("min"), max=raw.get("max")
                )
            elif isinstance(raw, bool):
                params_v1[name] = ParameterV1(type="bool", value=raw)
            else:
                # Fallback: treat as float-like
                params_v1[name] = ParameterV1(type="float", value=float(raw))

        # Sketches: convert V2-style back to V1 SketchGraph
        sketches_v1: List[SketchGraphV1] = []
        for s in self.sketches:
            primitives_v1 = [
                SketchPrimitiveV1(**p.model_dump()) for p in s.primitives
            ]
            constraints_v1 = [
                SketchConstraintV1(**c.model_dump()) for c in s.constraints
            ]
            sketches_v1.append(
                SketchGraphV1(
                    id=s.id,
                    plane=s.plane,
                    primitives=primitives_v1,
                    constraints=constraints_v1,
                )
            )

        # Features: project V3 features into the simpler V1 Feature
        features_v1: List[FeatureV1] = []
        for f in ordered_features:
            features_v1.append(
                FeatureV1(
                    id=f.id,
                    type=f.type,
                    sketch=getattr(f, "sketch", None),
                    targets=None,
                    params=dict(f.params),
                )
            )

        return FeatureGraphV1(
            schema_version="1.0",
            units=self.units,
            metadata=self.metadata,
            parameters=params_v1,
            sketches=sketches_v1,
            features=features_v1,
        )

    # ------------------------------------------------------------------
    # Dataset / dict helpers
    # ------------------------------------------------------------------

    def to_dataset_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary for dataset logging.

        This mirrors the V2-style shape (`version`, `parameters`,
        `sketches`, `features`) but uses version "3.0" and includes
        the new `constraints` array.
        """

        return {
            "version": self.version,
            "units": self.units,
            "metadata": self.metadata,
            "parameters": self.parameters,
            "sketches": [s.model_dump() for s in self.sketches],
            "features": [f.model_dump() for f in self.features],
            "constraints": [c.model_dump() for c in self.constraints],
        }
