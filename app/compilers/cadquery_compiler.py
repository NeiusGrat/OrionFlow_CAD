"""
CadQuery Compiler - FeatureGraphV1 → STEP/STL/GLB

Compiles the Canonical Feature Graph (CFG) into manufacturing artifacts using CadQuery.
- STEP: Exact B-Rep for manufacturing
- STL: Tessellated mesh for printing/rendering
- GLB: Web-optimized format for Three.js viewer

CadQuery is preferred over Build123d for:
- Better LLM compatibility (more documentation/examples in training data)
- Production maturity and stability
- Cleaner API for complex operations
"""
import logging
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, Union

import cadquery as cq
import trimesh

from app.domain.feature_graph_v1 import (
    FeatureGraphV1, 
    SketchGraph, 
    SketchPrimitive,
    Feature,
    Parameter
)
from app.domain.execution_trace import ExecutionTrace, TraceEvent
from app.compilers.v1.errors import SketchCompilationError, FeatureCompilationError

logger = logging.getLogger(__name__)


class CadQueryCompiler:
    """
    Compiles FeatureGraphV1 to CAD geometry using CadQuery.
    
    Pipeline:
    1. Compile sketches to CadQuery Workplane objects
    2. Apply features (extrude, fillet, chamfer)
    3. Export to STEP, STL, GLB
    
    Principles:
    - Deterministic: Same input always produces same output
    - Parametric: Resolves $param references from parameters dict
    - Traceable: Generates ExecutionTrace for debugging/retry
    """
    
    def __init__(self, output_dir: Path = Path("outputs")):
        """
        Initialize the CadQuery compiler.
        
        Args:
            output_dir: Directory for output geometry files
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"CadQueryCompiler initialized with output_dir={output_dir}")
    
    def compile(
        self, 
        feature_graph: FeatureGraphV1,
        job_id: str
    ) -> Tuple[Path, Path, Path, ExecutionTrace]:
        """
        Compile FeatureGraphV1 to geometry files.
        
        Main entry point for the compilation pipeline.
        
        Args:
            feature_graph: Validated FeatureGraphV1 instance
            job_id: Unique identifier for output filenames
            
        Returns:
            Tuple of (step_path, stl_path, glb_path, execution_trace)
            
        Raises:
            SketchCompilationError: If sketch compilation fails
            FeatureCompilationError: If feature application fails
        """
        events = []
        
        try:
            # Phase 1: Compile all sketches to CadQuery Workplanes
            sketches: Dict[str, cq.Workplane] = {}
            
            for sketch in feature_graph.sketches:
                events.append(TraceEvent(
                    stage=f"sketch_compile",
                    target=sketch.id,
                    status="pending"
                ))
                
                try:
                    wp = self._compile_sketch(sketch, feature_graph)
                    sketches[sketch.id] = wp
                    events[-1].status = "success"
                    logger.debug(f"Compiled sketch '{sketch.id}'")
                except Exception as e:
                    events[-1].status = "failure"
                    events[-1].message = str(e)
                    raise SketchCompilationError(f"Sketch '{sketch.id}' failed: {e}")
            
            # Phase 2: Apply 3D features sequentially
            result: Optional[cq.Workplane] = None
            
            for feature in feature_graph.features:
                events.append(TraceEvent(
                    stage=f"feature_{feature.type}",
                    target=feature.id,
                    status="pending"
                ))
                
                try:
                    result = self._apply_feature(
                        feature, 
                        sketches, 
                        feature_graph,
                        result
                    )
                    events[-1].status = "success"
                    logger.debug(f"Applied feature '{feature.id}' ({feature.type})")
                except Exception as e:
                    events[-1].status = "failure"
                    events[-1].message = str(e)
                    raise FeatureCompilationError(f"Feature '{feature.id}' failed: {e}")
            
            if result is None:
                raise FeatureCompilationError("No geometry produced - check features list")
            
            # Phase 3: Export to all formats
            events.append(TraceEvent(
                stage="export",
                target=None,
                status="pending"
            ))
            
            try:
                step_path = self._export_step(result, job_id)
                stl_path = self._export_stl(result, job_id)
                glb_path = self._convert_to_glb(stl_path, job_id)
                
                events[-1].status = "success"
                logger.info(f"Exported job '{job_id}' to STEP, STL, GLB")
            except Exception as e:
                events[-1].status = "failure"
                events[-1].message = str(e)
                raise
            
            trace = ExecutionTrace(
                success=True,
                events=events,
                retryable=False
            )
            
            return step_path, stl_path, glb_path, trace
            
        except Exception as e:
            logger.error(f"Compilation failed for job '{job_id}': {e}")
            trace = ExecutionTrace(
                success=False,
                events=events,
                retryable=True  # Schema/compiler errors may be retryable
            )
            raise
    
    def _compile_sketch(
        self, 
        sketch: SketchGraph, 
        graph: FeatureGraphV1
    ) -> cq.Workplane:
        """
        Compile a SketchGraph to CadQuery Workplane.
        
        Creates 2D geometry on the specified plane.
        
        Args:
            sketch: SketchGraph with primitives and constraints
            graph: Parent FeatureGraphV1 for parameter resolution
            
        Returns:
            CadQuery Workplane with sketch geometry
        """
        # Map plane name to CadQuery plane
        plane_map = {
            "XY": "XY",
            "YZ": "YZ", 
            "XZ": "XZ"
        }
        plane = plane_map.get(sketch.plane, "XY")
        
        # Start with workplane on specified plane
        wp = cq.Workplane(plane)
        
        for primitive in sketch.primitives:
            # Get params - support both .params (actual) and .parameters (legacy)
            params = self._get_primitive_params(primitive)
            
            if primitive.type == "rectangle":
                wp = self._add_rectangle(wp, params, graph)
                
            elif primitive.type == "circle":
                wp = self._add_circle(wp, params, graph)
                
            elif primitive.type == "line":
                wp = self._add_line(wp, params, graph)
                
            elif primitive.type == "arc":
                wp = self._add_arc(wp, params, graph)
                
            elif primitive.type == "point":
                # Points are typically construction geometry
                pass
                
            else:
                raise SketchCompilationError(
                    f"Unsupported primitive type: {primitive.type}"
                )
        
        return wp
    
    def _get_primitive_params(self, primitive: SketchPrimitive) -> Dict[str, Any]:
        """
        Get parameters from primitive with backward compatibility.
        
        Supports both:
        - primitive.params (actual FeatureGraphV1 schema)
        - primitive.parameters (legacy/migration format)
        
        Args:
            primitive: SketchPrimitive instance
            
        Returns:
            Parameters dictionary
        """
        # Primary: Use actual schema field
        if hasattr(primitive, 'params') and primitive.params:
            return primitive.params
        
        # Fallback: Legacy format for migration compatibility
        if hasattr(primitive, 'parameters') and primitive.parameters:
            logger.warning(f"Primitive '{primitive.id}' uses deprecated 'parameters' field")
            return primitive.parameters
        
        return {}
    
    def _add_rectangle(
        self, 
        wp: cq.Workplane, 
        params: Dict[str, Any],
        graph: FeatureGraphV1
    ) -> cq.Workplane:
        """Add centered rectangle to workplane."""
        width = self._resolve_param(params.get("width"), graph)
        height = self._resolve_param(params.get("height"), graph)
        
        # Optional center offset
        center_x = self._resolve_param(params.get("center_x", 0), graph)
        center_y = self._resolve_param(params.get("center_y", 0), graph)
        
        if center_x != 0 or center_y != 0:
            wp = wp.center(center_x, center_y)
        
        return wp.rect(width, height)
    
    def _add_circle(
        self, 
        wp: cq.Workplane, 
        params: Dict[str, Any],
        graph: FeatureGraphV1
    ) -> cq.Workplane:
        """Add circle to workplane."""
        radius = self._resolve_param(params.get("radius"), graph)
        
        # Optional center offset
        center_x = self._resolve_param(params.get("center_x", 0), graph)
        center_y = self._resolve_param(params.get("center_y", 0), graph)
        
        if center_x != 0 or center_y != 0:
            wp = wp.center(center_x, center_y)
        
        return wp.circle(radius)
    
    def _add_line(
        self, 
        wp: cq.Workplane, 
        params: Dict[str, Any],
        graph: FeatureGraphV1
    ) -> cq.Workplane:
        """Add line to workplane."""
        start_x = self._resolve_param(params.get("start_x", 0), graph)
        start_y = self._resolve_param(params.get("start_y", 0), graph)
        end_x = self._resolve_param(params.get("end_x"), graph)
        end_y = self._resolve_param(params.get("end_y"), graph)
        
        return wp.moveTo(start_x, start_y).lineTo(end_x, end_y)
    
    def _add_arc(
        self, 
        wp: cq.Workplane, 
        params: Dict[str, Any],
        graph: FeatureGraphV1
    ) -> cq.Workplane:
        """Add arc to workplane."""
        # Arc can be defined multiple ways - support common patterns
        if "radius" in params and "angle" in params:
            radius = self._resolve_param(params.get("radius"), graph)
            angle = self._resolve_param(params.get("angle"), graph)
            return wp.radiusArc((radius, 0), radius)
        
        # Three-point arc
        elif all(k in params for k in ["x1", "y1", "x2", "y2"]):
            x1 = self._resolve_param(params.get("x1"), graph)
            y1 = self._resolve_param(params.get("y1"), graph)
            x2 = self._resolve_param(params.get("x2"), graph)
            y2 = self._resolve_param(params.get("y2"), graph)
            return wp.threePointArc((x1, y1), (x2, y2))
        
        raise SketchCompilationError("Arc requires radius+angle or three-point definition")
    
    def _apply_feature(
        self, 
        feature: Feature,
        sketches: Dict[str, cq.Workplane],
        graph: FeatureGraphV1,
        current_solid: Optional[cq.Workplane]
    ) -> cq.Workplane:
        """
        Apply a 3D feature to geometry.
        
        Args:
            feature: Feature definition
            sketches: Compiled sketch workplanes by ID
            graph: Parent FeatureGraphV1 for parameter resolution
            current_solid: Existing solid to modify (or None for first feature)
            
        Returns:
            Modified CadQuery Workplane
        """
        # Get feature params
        params = feature.params
        
        if feature.type == "extrude":
            return self._apply_extrude(feature, sketches, graph, current_solid)
            
        elif feature.type == "fillet":
            return self._apply_fillet(feature, graph, current_solid)
            
        elif feature.type == "chamfer":
            return self._apply_chamfer(feature, graph, current_solid)
            
        elif feature.type == "revolve":
            return self._apply_revolve(feature, sketches, graph, current_solid)
            
        else:
            raise FeatureCompilationError(f"Unsupported feature type: {feature.type}")
    
    def _apply_extrude(
        self,
        feature: Feature,
        sketches: Dict[str, cq.Workplane],
        graph: FeatureGraphV1,
        current_solid: Optional[cq.Workplane]
    ) -> cq.Workplane:
        """Apply extrude operation."""
        sketch_id = feature.sketch
        if not sketch_id or sketch_id not in sketches:
            raise FeatureCompilationError(
                f"Extrude requires valid sketch reference, got: {sketch_id}"
            )
        
        wp = sketches[sketch_id]
        
        # Get extrusion depth - support both 'depth' and 'distance' keys
        depth = self._resolve_param(
            feature.params.get("depth") or feature.params.get("distance"),
            graph
        )
        
        if depth is None:
            raise FeatureCompilationError("Extrude requires 'depth' or 'distance' parameter")
        
        # Perform extrusion
        result = wp.extrude(depth)
        
        # Combine with existing solid if applicable
        if current_solid is not None:
            operation = feature.params.get("operation", "new")
            if operation == "union" or operation == "add":
                result = current_solid.union(result)
            elif operation == "subtract" or operation == "cut":
                result = current_solid.cut(result)
            elif operation == "intersect":
                result = current_solid.intersect(result)
            # "new" = replace current solid (default for first feature)
        
        return result
    
    def _apply_fillet(
        self,
        feature: Feature,
        graph: FeatureGraphV1,
        current_solid: Optional[cq.Workplane]
    ) -> cq.Workplane:
        """Apply fillet to edges."""
        if current_solid is None:
            raise FeatureCompilationError("Fillet requires existing solid geometry")
        
        radius = self._resolve_param(feature.params.get("radius"), graph)
        if radius is None:
            raise FeatureCompilationError("Fillet requires 'radius' parameter")
        
        # Edge selector - CadQuery syntax like ">Z", "<X", "|Y"
        edge_selector = feature.params.get("edge_selector", ">Z")
        
        # Handle targets for specific edge selection
        if feature.targets:
            # Custom edge targeting (advanced)
            logger.warning(f"Custom edge targets not fully implemented: {feature.targets}")
        
        try:
            return current_solid.edges(edge_selector).fillet(radius)
        except Exception as e:
            # Fallback: try all edges if selector fails
            logger.warning(f"Edge selector '{edge_selector}' failed, trying all edges: {e}")
            return current_solid.edges().fillet(radius)
    
    def _apply_chamfer(
        self,
        feature: Feature,
        graph: FeatureGraphV1,
        current_solid: Optional[cq.Workplane]
    ) -> cq.Workplane:
        """Apply chamfer to edges."""
        if current_solid is None:
            raise FeatureCompilationError("Chamfer requires existing solid geometry")
        
        distance = self._resolve_param(feature.params.get("distance"), graph)
        if distance is None:
            raise FeatureCompilationError("Chamfer requires 'distance' parameter")
        
        # Edge selector
        edge_selector = feature.params.get("edge_selector", ">Z")
        
        try:
            return current_solid.edges(edge_selector).chamfer(distance)
        except Exception as e:
            logger.warning(f"Edge selector '{edge_selector}' failed, trying all edges: {e}")
            return current_solid.edges().chamfer(distance)
    
    def _apply_revolve(
        self,
        feature: Feature,
        sketches: Dict[str, cq.Workplane],
        graph: FeatureGraphV1,
        current_solid: Optional[cq.Workplane]
    ) -> cq.Workplane:
        """Apply revolve operation."""
        sketch_id = feature.sketch
        if not sketch_id or sketch_id not in sketches:
            raise FeatureCompilationError(
                f"Revolve requires valid sketch reference, got: {sketch_id}"
            )
        
        wp = sketches[sketch_id]
        
        # Revolve angle in degrees
        angle = self._resolve_param(feature.params.get("angle", 360), graph)
        
        # Axis of revolution (default Y)
        axis = feature.params.get("axis", "Y")
        axis_vec = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}.get(axis, (0, 1, 0))
        
        result = wp.revolve(angle, axisStart=(0, 0, 0), axisEnd=axis_vec)
        
        if current_solid is not None:
            result = current_solid.union(result)
        
        return result
    
    def _resolve_param(
        self, 
        raw_value: Any, 
        graph: FeatureGraphV1
    ) -> Optional[float]:
        """
        Resolve parameter value from $reference or literal.
        
        Handles:
        - "$param_name" → looks up in graph.parameters
        - float/int → returns as-is
        - None → returns None
        
        Args:
            raw_value: Raw parameter value (string, number, or None)
            graph: FeatureGraphV1 for parameter lookup
            
        Returns:
            Resolved float value or None
        """
        if raw_value is None:
            return None
        
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        
        if isinstance(raw_value, str):
            # Handle $param_name references
            if raw_value.startswith("$"):
                param_name = raw_value[1:]  # Remove $ prefix
                
                if param_name in graph.parameters:
                    param = graph.parameters[param_name]
                    # Parameter is a Parameter object with .value
                    if isinstance(param, Parameter):
                        return float(param.value)
                    # Or might be raw dict during migration
                    elif isinstance(param, dict):
                        return float(param.get("value", 0))
                    else:
                        return float(param)
                else:
                    raise FeatureCompilationError(
                        f"Parameter reference '{raw_value}' not found in parameters"
                    )
            
            # Try parsing as float literal
            try:
                return float(raw_value)
            except ValueError:
                raise FeatureCompilationError(
                    f"Cannot resolve parameter value: {raw_value}"
                )
        
        return None
    
    def _export_step(self, solid: cq.Workplane, job_id: str) -> Path:
        """
        Export geometry to STEP format.
        
        STEP (AP214) is the standard format for manufacturing.
        
        Args:
            solid: CadQuery Workplane with solid geometry
            job_id: Unique identifier for filename
            
        Returns:
            Path to exported STEP file
        """
        path = self.output_dir / f"{job_id}.step"
        cq.exporters.export(solid, str(path), exportType="STEP")
        logger.debug(f"Exported STEP: {path}")
        return path
    
    def _export_stl(self, solid: cq.Workplane, job_id: str) -> Path:
        """
        Export geometry to STL format.
        
        STL is a tessellated mesh format for 3D printing.
        
        Args:
            solid: CadQuery Workplane with solid geometry
            job_id: Unique identifier for filename
            
        Returns:
            Path to exported STL file
        """
        path = self.output_dir / f"{job_id}.stl"
        cq.exporters.export(solid, str(path), exportType="STL")
        logger.debug(f"Exported STL: {path}")
        return path
    
    def _convert_to_glb(self, stl_path: Path, job_id: str) -> Path:
        """
        Convert STL to GLB for web viewer.
        
        GLB is the binary glTF format optimized for Three.js.
        
        Args:
            stl_path: Path to input STL file
            job_id: Unique identifier for filename
            
        Returns:
            Path to exported GLB file
        """
        glb_path = self.output_dir / f"{job_id}.glb"
        
        # Load STL with trimesh
        mesh = trimesh.load(str(stl_path))
        
        # Export as GLB (binary glTF)
        mesh.export(str(glb_path), file_type='glb')
        
        logger.debug(f"Converted to GLB: {glb_path}")
        return glb_path
