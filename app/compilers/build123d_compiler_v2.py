"""
Build123d Compiler V2 - Semantic Selector Support

Extends Build123dCompiler with semantic topology selector resolution.

Key features:
- Resolves SemanticSelector to Build123d edge/face selections
- Applies GeometricFilter chains (AND logic)
- Falls back to string selectors for simple cases
- Maintains backward compatibility with V1
"""
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any, Union

from build123d import (
    Solid, Compound, Part, Sketch, BuildPart, BuildSketch,
    extrude, fillet, chamfer, Axis, Plane, Mode, Location,
    export_step, export_stl, export_gltf,
    Rectangle, Circle, Vector, Edge, Face
)
import trimesh

from app.domain.feature_graph_v2 import (
    FeatureGraphV2, FeatureV2, SketchGraphV2,
    SemanticSelector, SelectorType, GeometricFilter, GeometricFilterType
)
from app.domain.execution_trace import ExecutionTrace, TraceEvent
from app.compilers.v1.errors import SketchCompilationError, FeatureCompilationError

logger = logging.getLogger(__name__)


class Build123dCompilerV2:
    """
    Compiles FeatureGraphV2 to CAD geometry using Build123d.
    
    Extends V1 compiler with semantic selector support.
    
    Pipeline:
    1. Compile sketches to Build123d Sketch objects
    2. Apply features with semantic topology selection
    3. Export to STEP, STL, GLB
    """
    
    def __init__(self, output_dir: Path = Path("outputs")):
        """Initialize the compiler with output directory."""
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Build123dCompilerV2 initialized with output_dir={output_dir}")
    
    def compile(
        self,
        feature_graph: FeatureGraphV2,
        job_id: str
    ) -> Tuple[Path, Path, Path, ExecutionTrace]:
        """
        Compile FeatureGraphV2 to geometry files.
        
        Args:
            feature_graph: Validated FeatureGraphV2 instance
            job_id: Unique identifier for output files
            
        Returns:
            Tuple of (step_path, stl_path, glb_path, execution_trace)
        """
        events = []
        
        try:
            # Phase 1: Compile all sketches
            sketches: Dict[str, Any] = {}
            
            for sketch_def in feature_graph.sketches:
                events.append(TraceEvent(
                    stage="sketch_compile",
                    target=sketch_def.id,
                    status="pending"
                ))
                
                try:
                    sketch = self._compile_sketch(sketch_def, feature_graph)
                    sketches[sketch_def.id] = sketch
                    events[-1].status = "success"
                except Exception as e:
                    events[-1].status = "failure"
                    events[-1].message = str(e)
                    raise SketchCompilationError(f"Sketch '{sketch_def.id}': {e}")
            
            # Phase 2: Apply features sequentially
            solid = None
            
            for feature in feature_graph.features:
                events.append(TraceEvent(
                    stage=f"feature_{feature.type}",
                    target=feature.id,
                    status="pending"
                ))
                
                try:
                    solid = self._apply_feature_v2(feature, sketches, feature_graph, solid)
                    events[-1].status = "success"
                except Exception as e:
                    events[-1].status = "failure"
                    events[-1].message = str(e)
                    raise FeatureCompilationError(f"Feature '{feature.id}': {e}")
            
            if solid is None:
                raise FeatureCompilationError("No geometry produced")
            
            # Phase 3: Export
            events.append(TraceEvent(stage="export", target=None, status="pending"))
            
            step_path = self.output_dir / f"{job_id}.step"
            stl_path = self.output_dir / f"{job_id}.stl"
            glb_path = self.output_dir / f"{job_id}.glb"
            
            export_step(solid, str(step_path))
            export_stl(solid, str(stl_path))
            export_gltf(solid, str(glb_path))
            
            events[-1].status = "success"
            
            trace = ExecutionTrace(success=True, events=events, retryable=False)
            return step_path, stl_path, glb_path, trace
            
        except Exception as e:
            logger.error(f"V2 Compilation failed: {e}")
            trace = ExecutionTrace(success=False, events=events, retryable=True)
            raise
    
    def _compile_sketch(
        self,
        sketch_def: SketchGraphV2,
        graph: FeatureGraphV2
    ) -> Any:
        """Compile SketchGraphV2 to Build123d Sketch."""
        plane_map = {
            "XY": Plane.XY,
            "YZ": Plane.YZ,
            "XZ": Plane.XZ
        }
        plane = plane_map.get(sketch_def.plane, Plane.XY)
        
        with BuildSketch(plane) as sketch:
            for primitive in sketch_def.primitives:
                params = primitive.params
                
                if primitive.type == "rectangle":
                    width = self._resolve_param(params.get("width"), graph)
                    height = self._resolve_param(params.get("height"), graph)
                    Rectangle(width, height)
                    
                elif primitive.type == "circle":
                    radius = self._resolve_param(params.get("radius"), graph)
                    Circle(radius)
                    
                # Add more primitives as needed
        
        return sketch
    
    def _apply_feature_v2(
        self,
        feature: FeatureV2,
        sketches: Dict[str, Any],
        graph: FeatureGraphV2,
        current_solid: Optional[Solid]
    ) -> Solid:
        """Apply a V2 feature with semantic selector support."""
        
        if feature.type == "extrude":
            sketch_id = feature.sketch
            if sketch_id not in sketches:
                raise FeatureCompilationError(f"Sketch '{sketch_id}' not found")
            
            depth = self._resolve_param(
                feature.params.get("depth") or feature.params.get("distance"),
                graph
            )
            
            # Get the sketch geometry
            sketch_builder = sketches[sketch_id]
            target_geo = sketch_builder.sketch if hasattr(sketch_builder, "sketch") else sketch_builder
            
            # Extrude the sketch
            new_solid = extrude(target_geo, amount=depth)
            
            # Combine with existing solid if applicable
            if current_solid is None:
                return new_solid
            else:
                return current_solid + new_solid
            
        elif feature.type == "fillet":
            if current_solid is None:
                raise FeatureCompilationError("Fillet requires existing geometry")
            
            radius = self._resolve_param(feature.params.get("radius"), graph)
            
            # Get edges using semantic selector
            edges = self._get_edges_from_topology_refs(
                feature.topology_refs,
                current_solid,
                graph
            )
            
            if edges:
                return fillet(current_solid.edges().filter_by(lambda e: e in edges), radius=radius)
            else:
                # Fallback: fillet all edges
                logger.warning("No edges selected for fillet, using all edges")
                return fillet(current_solid.edges(), radius=radius)
            
        elif feature.type == "chamfer":
            if current_solid is None:
                raise FeatureCompilationError("Chamfer requires existing geometry")
            
            distance = self._resolve_param(feature.params.get("distance"), graph)
            
            edges = self._get_edges_from_topology_refs(
                feature.topology_refs,
                current_solid,
                graph
            )
            
            if edges:
                return chamfer(current_solid.edges().filter_by(lambda e: e in edges), length=distance)
            else:
                return chamfer(current_solid.edges(), length=distance)
            
        else:
            raise FeatureCompilationError(f"Unsupported feature type: {feature.type}")
    
    def _get_edges_from_topology_refs(
        self,
        topology_refs: Optional[Dict[str, SemanticSelector]],
        solid: Solid,
        graph: FeatureGraphV2
    ) -> List[Edge]:
        """
        Extract edges from topology references using semantic selectors.
        
        Args:
            topology_refs: Dict of named selectors (e.g., {"edges": SemanticSelector})
            solid: Current solid geometry
            graph: Feature graph for parameter resolution
            
        Returns:
            List of selected edges
        """
        if not topology_refs:
            return []
        
        # Look for common edge selector keys
        for key in ["edges", "target_edges", "edge_selector"]:
            if key in topology_refs:
                selector = topology_refs[key]
                return self._resolve_semantic_selector(selector, solid, graph)
        
        return []
    
    def _resolve_semantic_selector(
        self,
        selector: Union[SemanticSelector, dict],
        solid: Solid,
        graph: FeatureGraphV2
    ) -> List[Edge]:
        """
        Resolve a semantic selector to actual edges.
        
        Args:
            selector: SemanticSelector or dict representation
            solid: Current solid to select from
            graph: Feature graph for parameter resolution
            
        Returns:
            List of selected edges
        """
        # Handle dict input (from JSON)
        if isinstance(selector, dict):
            selector = SemanticSelector(**selector)
        
        if selector.selector_type == SelectorType.STRING:
            # Use Build123d's selector syntax
            return self._select_edges_by_string(solid, selector.string_selector)
        
        elif selector.selector_type in [SelectorType.SEMANTIC, SelectorType.FILTER_CHAIN]:
            # Apply filters sequentially
            candidates = list(solid.edges())
            
            for filter_def in (selector.filters or []):
                if isinstance(filter_def, dict):
                    filter_def = GeometricFilter(**filter_def)
                candidates = self._apply_filter(candidates, filter_def, solid)
            
            return candidates
        
        elif selector.selector_type == SelectorType.REFERENCE:
            # Reference-based selection (VERSION 0.4)
            logger.warning("Reference selectors not yet implemented")
            return []
        
        return []
    
    def _select_edges_by_string(self, solid: Solid, selector: str) -> List[Edge]:
        """
        Select edges using Build123d selector string.
        
        Common selectors:
        - ">Z" : Edges with highest Z (top)
        - "<Z" : Edges with lowest Z (bottom)
        - "|Z" : Edges parallel to Z axis
        - ">X" : Edges with highest X
        """
        try:
            # Build123d edge selection syntax
            if selector.startswith(">"):
                axis = selector[1]
                if axis == "Z":
                    # Top edges - filter by Z position
                    edges = list(solid.edges())
                    if not edges:
                        return []
                    max_z = max(e.center().Z for e in edges)
                    return [e for e in edges if abs(e.center().Z - max_z) < 0.01]
                elif axis == "X":
                    edges = list(solid.edges())
                    if not edges:
                        return []
                    max_x = max(e.center().X for e in edges)
                    return [e for e in edges if abs(e.center().X - max_x) < 0.01]
                elif axis == "Y":
                    edges = list(solid.edges())
                    if not edges:
                        return []
                    max_y = max(e.center().Y for e in edges)
                    return [e for e in edges if abs(e.center().Y - max_y) < 0.01]
            
            elif selector.startswith("<"):
                axis = selector[1]
                if axis == "Z":
                    edges = list(solid.edges())
                    if not edges:
                        return []
                    min_z = min(e.center().Z for e in edges)
                    return [e for e in edges if abs(e.center().Z - min_z) < 0.01]
                # Add X, Y...
            
            elif selector.startswith("|"):
                axis = selector[1]
                axis_vec = self._axis_vector(axis)
                edges = list(solid.edges())
                return [e for e in edges if self._is_parallel_to_axis(e, axis_vec)]
            
            # Fallback: return all edges
            logger.warning(f"Unknown selector '{selector}', returning all edges")
            return list(solid.edges())
            
        except Exception as e:
            logger.error(f"Edge selection failed: {e}")
            return list(solid.edges())
    
    def _apply_filter(
        self,
        edges: List[Edge],
        filter_def: GeometricFilter,
        solid: Solid
    ) -> List[Edge]:
        """Apply a geometric filter to edge candidates."""
        
        filter_type = filter_def.type
        params = filter_def.parameters
        
        if filter_type == GeometricFilterType.PARALLEL_TO_AXIS:
            axis = params.get("axis", "Z")
            axis_vec = self._axis_vector(axis)
            return [e for e in edges if self._is_parallel_to_axis(e, axis_vec)]
        
        elif filter_type == GeometricFilterType.PERPENDICULAR_TO_AXIS:
            axis = params.get("axis", "Z")
            axis_vec = self._axis_vector(axis)
            return [e for e in edges if self._is_perpendicular_to_axis(e, axis_vec)]
        
        elif filter_type == GeometricFilterType.ON_FACE:
            face_selector = params.get("face_selector", ">Z")
            faces = self._select_faces_by_string(solid, face_selector)
            return [e for e in edges if self._edge_on_face(e, faces)]
        
        elif filter_type == GeometricFilterType.LENGTH_RANGE:
            min_len = params.get("min", 0)
            max_len = params.get("max", float("inf"))
            return [e for e in edges if min_len <= e.length <= max_len]
        
        elif filter_type == GeometricFilterType.DIRECTION:
            direction = params.get("direction", [1, 0, 0])
            return [e for e in edges if self._edge_in_direction(e, direction)]
        
        # Unknown filter - pass through
        logger.warning(f"Unknown filter type: {filter_type}")
        return edges
    
    def _select_faces_by_string(self, solid: Solid, selector: str) -> List[Face]:
        """Select faces using string selector."""
        faces = list(solid.faces())
        
        if selector.startswith(">Z"):
            if not faces:
                return []
            max_z = max(f.center().Z for f in faces)
            return [f for f in faces if abs(f.center().Z - max_z) < 0.01]
        elif selector.startswith("<Z"):
            if not faces:
                return []
            min_z = min(f.center().Z for f in faces)
            return [f for f in faces if abs(f.center().Z - min_z) < 0.01]
        
        return faces
    
    def _edge_on_face(self, edge: Edge, faces: List[Face]) -> bool:
        """Check if edge is on any of the given faces."""
        edge_center = edge.center()
        for face in faces:
            # Simple proximity check - edge center near face
            face_center = face.center()
            # Check if on same plane (simplified)
            if abs(edge_center.Z - face_center.Z) < 0.01:
                return True
        return False
    
    def _is_parallel_to_axis(self, edge: Edge, axis_vec: Vector) -> bool:
        """Check if edge is parallel to axis vector."""
        try:
            # Get edge direction
            edge_vec = edge.tangent_at(0)
            # Normalized dot product should be ~1 for parallel
            dot = abs(edge_vec.dot(axis_vec))
            return dot > 0.99
        except:
            return False
    
    def _is_perpendicular_to_axis(self, edge: Edge, axis_vec: Vector) -> bool:
        """Check if edge is perpendicular to axis vector."""
        try:
            edge_vec = edge.tangent_at(0)
            dot = abs(edge_vec.dot(axis_vec))
            return dot < 0.01
        except:
            return False
    
    def _edge_in_direction(self, edge: Edge, direction: List[float]) -> bool:
        """Check if edge points in given direction."""
        try:
            edge_vec = edge.tangent_at(0)
            dir_vec = Vector(direction[0], direction[1], direction[2]).normalized()
            dot = abs(edge_vec.dot(dir_vec))
            return dot > 0.99
        except:
            return False
    
    def _axis_vector(self, axis: str) -> Vector:
        """Get unit vector for axis name."""
        return {
            "X": Vector(1, 0, 0),
            "Y": Vector(0, 1, 0),
            "Z": Vector(0, 0, 1)
        }.get(axis.upper(), Vector(0, 0, 1))
    
    def _resolve_param(self, raw_value: Any, graph: FeatureGraphV2) -> Optional[float]:
        """Resolve parameter value from $reference or literal."""
        if raw_value is None:
            return None
        
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        
        if isinstance(raw_value, str):
            if raw_value.startswith("$"):
                param_name = raw_value[1:]
                if param_name in graph.parameters:
                    param = graph.parameters[param_name]
                    if isinstance(param, dict):
                        return float(param.get("value", param.get("default", 0)))
                    # Handle direct value (float/int)
                    return float(param)
                raise FeatureCompilationError(f"Parameter '{raw_value}' not found")
            
            try:
                return float(raw_value)
            except ValueError:
                raise FeatureCompilationError(f"Cannot parse: {raw_value}")
        
        return None
