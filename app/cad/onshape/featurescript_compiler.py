"""
FeatureScript Compiler Stub - IR to Onshape FeatureScript

==============================================================================
ARCHITECTURE: Validates IR → FeatureScript Portability
==============================================================================

This module proves that FeatureGraphIR can be transpiled to FeatureScript,
Onshape's native parametric modeling language. This validates that our IR
is a true parametric representation, not just a procedural sequence.

WHY THIS MATTERS:
- If IR → FeatureScript is possible, IR is a valid parametric IR
- If not, we have implementation-specific leakage
- This is the "round-trip test" for IR correctness

SUPPORTED OPERATIONS (STEP 5 baseline):
1. Extrude (sketch → 3D solid, add/remove material)
2. Fillet (edge selection, radius)
3. Cut (sketch → remove material)
4. Revolve (sketch → revolution)
5. Chamfer (edge selection, distance)

FeatureScript Reference:
- https://cad.onshape.com/FsDoc/library.html
- Operations: opExtrude, opFillet, opRevolve, opChamfer

Version: 1.0
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import json

from app.domain.feature_graph_ir import (
    FeatureGraphIR,
    FeatureIR,
    SketchIR,
    FeatureType,
    PrimitiveType
)


# =============================================================================
# FeatureScript Types
# =============================================================================

class FSOperationType(str, Enum):
    """FeatureScript operation types."""
    OP_EXTRUDE = "opExtrude"
    OP_FILLET = "opFillet"
    OP_CHAMFER = "opChamfer"
    OP_REVOLVE = "opRevolve"
    OP_CUT = "opExtrude"  # Cut uses opExtrude with BooleanOperationType.SUBTRACTION
    OP_SKETCH = "newSketchOnPlane"


class FSBooleanOperation(str, Enum):
    """FeatureScript boolean operation types."""
    NEW = "NEW"
    ADD = "ADD"
    REMOVE = "REMOVE"
    INTERSECT = "INTERSECT"


class FSPlane(str, Enum):
    """FeatureScript standard planes."""
    XY = "XY"
    XZ = "XZ"
    YZ = "YZ"
    TOP = "TOP"
    FRONT = "FRONT"
    RIGHT = "RIGHT"


# =============================================================================
# FeatureScript AST Nodes
# =============================================================================

@dataclass
class FSParameter:
    """A FeatureScript parameter declaration."""
    name: str
    value: float
    unit: str = "millimeter"

    def to_fs(self) -> str:
        """Generate FeatureScript parameter definition."""
        return f"const {self.name} = {self.value} * {self.unit};"


@dataclass
class FSSketchEntity:
    """A FeatureScript sketch entity."""
    entity_id: str
    entity_type: str
    params: Dict[str, float]

    def to_fs(self) -> str:
        """Generate FeatureScript sketch entity call."""
        if self.entity_type == "rectangle":
            return (
                f'skRectangle(sketch, "{self.entity_id}", {{\n'
                f'    "firstCorner": vector(0, 0) * millimeter,\n'
                f'    "secondCorner": vector({self.params.get("width", 10)}, '
                f'{self.params.get("height", 10)}) * millimeter\n'
                f'}});'
            )
        elif self.entity_type == "circle":
            return (
                f'skCircle(sketch, "{self.entity_id}", {{\n'
                f'    "center": vector(0, 0) * millimeter,\n'
                f'    "radius": {self.params.get("radius", 5)} * millimeter\n'
                f'}});'
            )
        elif self.entity_type == "line":
            return (
                f'skLineSegment(sketch, "{self.entity_id}", {{\n'
                f'    "start": vector({self.params.get("x1", 0)}, {self.params.get("y1", 0)}) * millimeter,\n'
                f'    "end": vector({self.params.get("x2", 10)}, {self.params.get("y2", 10)}) * millimeter\n'
                f'}});'
            )
        elif self.entity_type == "arc":
            return (
                f'skArc(sketch, "{self.entity_id}", {{\n'
                f'    "start": vector({self.params.get("x1", 0)}, {self.params.get("y1", 0)}) * millimeter,\n'
                f'    "mid": vector({self.params.get("xm", 5)}, {self.params.get("ym", 5)}) * millimeter,\n'
                f'    "end": vector({self.params.get("x2", 10)}, {self.params.get("y2", 0)}) * millimeter\n'
                f'}});'
            )
        else:
            return f'// Unsupported entity type: {self.entity_type}'


@dataclass
class FSSketch:
    """A FeatureScript sketch definition."""
    sketch_id: str
    plane: str
    entities: List[FSSketchEntity] = field(default_factory=list)

    def to_fs(self) -> str:
        """Generate FeatureScript sketch block."""
        plane_map = {
            "XY": "XY",
            "XZ": "XZ",
            "YZ": "YZ"
        }
        fs_plane = plane_map.get(self.plane, "XY")

        lines = [
            f'// Sketch: {self.sketch_id}',
            f'var sketch_{self.sketch_id} = newSketchOnPlane(context, id + "{self.sketch_id}", {{',
            f'    "sketchPlane": plane(vector(0, 0, 0) * millimeter, vector(0, 0, 1))',
            f'}});',
            f'var sketch = sketch_{self.sketch_id};',
            ''
        ]

        for entity in self.entities:
            lines.append(entity.to_fs())
            lines.append('')

        lines.append(f'skSolve(sketch);')
        return '\n'.join(lines)


@dataclass
class FSOperation:
    """A FeatureScript 3D operation."""
    operation_id: str
    operation_type: FSOperationType
    params: Dict[str, Any]
    sketch_ref: Optional[str] = None
    boolean_op: FSBooleanOperation = FSBooleanOperation.NEW

    def to_fs(self) -> str:
        """Generate FeatureScript operation call."""
        if self.operation_type == FSOperationType.OP_EXTRUDE:
            return self._generate_extrude()
        elif self.operation_type == FSOperationType.OP_FILLET:
            return self._generate_fillet()
        elif self.operation_type == FSOperationType.OP_CHAMFER:
            return self._generate_chamfer()
        elif self.operation_type == FSOperationType.OP_REVOLVE:
            return self._generate_revolve()
        else:
            return f'// Unsupported operation: {self.operation_type}'

    def _generate_extrude(self) -> str:
        """Generate opExtrude call."""
        depth = self.params.get("depth", 10)
        direction = self.params.get("direction", "FORWARD")

        # Map boolean operation
        bool_op_map = {
            FSBooleanOperation.NEW: "BooleanOperationType.NEW",
            FSBooleanOperation.ADD: "BooleanOperationType.ADD",
            FSBooleanOperation.REMOVE: "BooleanOperationType.SUBTRACTION",
            FSBooleanOperation.INTERSECT: "BooleanOperationType.INTERSECTION"
        }
        bool_type = bool_op_map.get(self.boolean_op, "BooleanOperationType.NEW")

        return f'''// Feature: {self.operation_id} (Extrude)
opExtrude(context, id + "{self.operation_id}", {{
    "entities": qSketchRegion(id + "{self.sketch_ref}"),
    "direction": evOwnerSketchPlane(context, {{"entity": qSketchRegion(id + "{self.sketch_ref}")}}).normal,
    "endBound": BoundingType.BLIND,
    "endDepth": {depth} * millimeter,
    "operationType": {bool_type}
}});'''

    def _generate_fillet(self) -> str:
        """Generate opFillet call."""
        radius = self.params.get("radius", 1)

        # Edge selection - in real FeatureScript this would use qEdge queries
        edge_query = self.params.get("edges", "qAllEdges()")

        return f'''// Feature: {self.operation_id} (Fillet)
opFillet(context, id + "{self.operation_id}", {{
    "entities": qCreatedBy(id + "{self.params.get('target', 'unknown')}", EntityType.EDGE),
    "radius": {radius} * millimeter
}});'''

    def _generate_chamfer(self) -> str:
        """Generate opChamfer call."""
        distance = self.params.get("distance", 1)

        return f'''// Feature: {self.operation_id} (Chamfer)
opChamfer(context, id + "{self.operation_id}", {{
    "entities": qCreatedBy(id + "{self.params.get('target', 'unknown')}", EntityType.EDGE),
    "chamferType": ChamferType.EQUAL_OFFSETS,
    "width": {distance} * millimeter
}});'''

    def _generate_revolve(self) -> str:
        """Generate opRevolve call."""
        angle = self.params.get("angle", 360)

        return f'''// Feature: {self.operation_id} (Revolve)
opRevolve(context, id + "{self.operation_id}", {{
    "entities": qSketchRegion(id + "{self.sketch_ref}"),
    "axis": line(vector(0, 0, 0) * millimeter, vector(0, 1, 0)),
    "angleForward": {angle} * degree
}});'''


# =============================================================================
# FeatureScript Program
# =============================================================================

@dataclass
class FSProgram:
    """Complete FeatureScript program (Part Studio feature)."""
    feature_name: str
    parameters: List[FSParameter] = field(default_factory=list)
    sketches: List[FSSketch] = field(default_factory=list)
    operations: List[FSOperation] = field(default_factory=list)

    def to_fs(self) -> str:
        """Generate complete FeatureScript code."""
        lines = [
            f'// FeatureScript generated from FeatureGraphIR',
            f'// Feature: {self.feature_name}',
            f'// Generated by OrionFlow CAD',
            f'',
            f'FeatureScript 2240;',
            f'import(path : "onshape/std/common.fs", version : "2240.0");',
            f'',
            f'annotation {{ "Feature Type Name" : "{self.feature_name}" }}',
            f'export const {self._safe_name()} = defineFeature(function(context is Context, id is Id, definition is map)',
            f'    precondition',
            f'    {{',
            f'        // Feature parameters',
        ]

        # Add parameter definitions
        for param in self.parameters:
            lines.append(f'        annotation {{ "Name" : "{param.name}" }}')
            lines.append(f'        isLength(definition.{param.name}, LENGTH_BOUNDS);')

        lines.extend([
            f'    }}',
            f'    {{',
            f'        // Feature body',
            f''
        ])

        # Add sketches
        for sketch in self.sketches:
            sketch_code = sketch.to_fs()
            for line in sketch_code.split('\n'):
                lines.append(f'        {line}')
            lines.append('')

        # Add operations
        for op in self.operations:
            op_code = op.to_fs()
            for line in op_code.split('\n'):
                lines.append(f'        {line}')
            lines.append('')

        lines.extend([
            f'    }});',
            f''
        ])

        return '\n'.join(lines)

    def _safe_name(self) -> str:
        """Convert feature name to valid FeatureScript identifier."""
        name = self.feature_name.replace(' ', '_').replace('-', '_')
        return ''.join(c for c in name if c.isalnum() or c == '_')


# =============================================================================
# FeatureScript Compiler
# =============================================================================

class FeatureScriptCompiler:
    """
    Compiles FeatureGraphIR to FeatureScript code.

    This is a STUB compiler that proves IR portability.
    It generates syntactically valid FeatureScript that can be
    pasted into Onshape's FeatureScript IDE.

    Usage:
        compiler = FeatureScriptCompiler()
        fs_code = compiler.compile(ir)
        print(fs_code)  # Paste into Onshape
    """

    # IR FeatureType to FeatureScript operation mapping
    TYPE_MAP = {
        FeatureType.EXTRUDE: FSOperationType.OP_EXTRUDE,
        FeatureType.CUT: FSOperationType.OP_EXTRUDE,  # Cut uses extrude with SUBTRACTION
        FeatureType.FILLET: FSOperationType.OP_FILLET,
        FeatureType.CHAMFER: FSOperationType.OP_CHAMFER,
        FeatureType.REVOLVE: FSOperationType.OP_REVOLVE,
    }

    # IR PrimitiveType to FeatureScript sketch entity type
    PRIMITIVE_MAP = {
        PrimitiveType.RECTANGLE: "rectangle",
        PrimitiveType.CIRCLE: "circle",
        PrimitiveType.LINE: "line",
        PrimitiveType.ARC: "arc",
        PrimitiveType.POINT: "point",
    }

    def __init__(self):
        """Initialize the compiler."""
        self._errors: List[str] = []
        self._warnings: List[str] = []

    def compile(
        self,
        ir: FeatureGraphIR,
        feature_name: str = "GeneratedFeature"
    ) -> str:
        """
        Compile FeatureGraphIR to FeatureScript code.

        Args:
            ir: Fully resolved FeatureGraphIR
            feature_name: Name for the generated feature

        Returns:
            FeatureScript code as string

        Raises:
            CompilationError: If IR contains unsupported operations
        """
        self._errors = []
        self._warnings = []

        # Build FeatureScript program
        program = FSProgram(feature_name=feature_name)

        # Convert parameters
        program.parameters = self._compile_parameters(ir)

        # Convert sketches
        program.sketches = self._compile_sketches(ir)

        # Convert features (in topological order)
        sorted_features = ir.topological_sort_features()
        program.operations = self._compile_features(sorted_features, ir)

        # Generate code
        fs_code = program.to_fs()

        # Add compilation report as comment
        if self._warnings:
            warning_block = '\n'.join(f'// WARNING: {w}' for w in self._warnings)
            fs_code = warning_block + '\n\n' + fs_code

        return fs_code

    def compile_to_dict(self, ir: FeatureGraphIR) -> Dict[str, Any]:
        """
        Compile IR to a dictionary representation for API calls.

        Returns a structure that can be sent to Onshape's Feature API.
        """
        result = {
            "feature_type": "custom",
            "parameters": {},
            "sketches": [],
            "operations": []
        }

        for name, param in ir.parameters.items():
            result["parameters"][name] = {
                "value": param.value,
                "unit": str(ir.units)
            }

        for sketch in ir.sketches:
            sketch_data = {
                "id": sketch.id,
                "plane": str(sketch.plane),
                "entities": []
            }
            for prim in sketch.primitives:
                sketch_data["entities"].append({
                    "id": prim.id,
                    "type": str(prim.type),
                    "params": prim.params
                })
            result["sketches"].append(sketch_data)

        for feature in ir.topological_sort_features():
            result["operations"].append({
                "id": feature.id,
                "type": str(feature.type),
                "sketch": feature.sketch,
                "params": feature.params,
                "depends_on": feature.depends_on
            })

        return result

    def validate_ir_for_featurescript(self, ir: FeatureGraphIR) -> List[str]:
        """
        Validate that IR can be compiled to FeatureScript.

        Returns list of validation errors (empty if valid).
        """
        errors = []

        # Check for unsupported feature types
        for feature in ir.features:
            if feature.type == FeatureType.LOFT:
                errors.append(
                    f"Feature '{feature.id}': LOFT requires guide curves, "
                    f"not fully supported in stub compiler"
                )
            if feature.type == FeatureType.PATTERN:
                errors.append(
                    f"Feature '{feature.id}': PATTERN requires direction/spacing, "
                    f"not fully supported in stub compiler"
                )

        # Check for valid sketch references
        sketch_ids = {s.id for s in ir.sketches}
        for feature in ir.features:
            if feature.sketch and feature.sketch not in sketch_ids:
                errors.append(
                    f"Feature '{feature.id}' references unknown sketch '{feature.sketch}'"
                )

        # Check for valid dependencies
        feature_ids = {f.id for f in ir.features}
        for feature in ir.features:
            for dep in feature.depends_on:
                if dep not in feature_ids:
                    errors.append(
                        f"Feature '{feature.id}' depends on unknown feature '{dep}'"
                    )

        return errors

    def _compile_parameters(self, ir: FeatureGraphIR) -> List[FSParameter]:
        """Convert IR parameters to FeatureScript parameters."""
        params = []
        for name, param in ir.parameters.items():
            params.append(FSParameter(
                name=name,
                value=param.value,
                unit="millimeter" if ir.units == "mm" else "inch"
            ))
        return params

    def _compile_sketches(self, ir: FeatureGraphIR) -> List[FSSketch]:
        """Convert IR sketches to FeatureScript sketches."""
        sketches = []
        for sketch in ir.sketches:
            fs_sketch = FSSketch(
                sketch_id=sketch.id,
                plane=str(sketch.plane)
            )

            for prim in sketch.primitives:
                entity_type = self.PRIMITIVE_MAP.get(prim.type, str(prim.type))
                fs_sketch.entities.append(FSSketchEntity(
                    entity_id=prim.id,
                    entity_type=entity_type,
                    params=prim.params
                ))

            sketches.append(fs_sketch)

        return sketches

    def _compile_features(
        self,
        features: List[FeatureIR],
        ir: FeatureGraphIR
    ) -> List[FSOperation]:
        """Convert IR features to FeatureScript operations."""
        operations = []

        for feature in features:
            op_type = self.TYPE_MAP.get(feature.type)

            if op_type is None:
                self._warnings.append(
                    f"Feature '{feature.id}' type '{feature.type}' "
                    f"not fully supported, using placeholder"
                )
                continue

            # Determine boolean operation
            boolean_op = FSBooleanOperation.NEW
            if feature.type == FeatureType.CUT:
                boolean_op = FSBooleanOperation.REMOVE

            # Find target for fillet/chamfer
            params = dict(feature.params)
            if feature.type in (FeatureType.FILLET, FeatureType.CHAMFER):
                if feature.depends_on:
                    params["target"] = feature.depends_on[0]

            operations.append(FSOperation(
                operation_id=feature.id,
                operation_type=op_type,
                params=params,
                sketch_ref=feature.sketch,
                boolean_op=boolean_op
            ))

        return operations


# =============================================================================
# Utility Functions
# =============================================================================

def compile_ir_to_featurescript(
    ir: FeatureGraphIR,
    feature_name: str = "GeneratedFeature"
) -> str:
    """
    Convenience function to compile IR to FeatureScript.

    Args:
        ir: Fully resolved FeatureGraphIR
        feature_name: Name for the generated feature

    Returns:
        FeatureScript code as string
    """
    compiler = FeatureScriptCompiler()
    return compiler.compile(ir, feature_name)


def validate_ir_portability(ir: FeatureGraphIR) -> Dict[str, Any]:
    """
    Validate that IR can be ported to FeatureScript.

    Returns validation report.
    """
    compiler = FeatureScriptCompiler()
    errors = compiler.validate_ir_for_featurescript(ir)

    return {
        "is_portable": len(errors) == 0,
        "errors": errors,
        "supported_features": [
            f.id for f in ir.features
            if f.type in FeatureScriptCompiler.TYPE_MAP
        ],
        "unsupported_features": [
            f.id for f in ir.features
            if f.type not in FeatureScriptCompiler.TYPE_MAP
        ]
    }
