"""
Build123d Compiler V3 - Topological Identity Tracking

Extends Build123dCompilerV2 with deterministic entity selection using
metadata tagging instead of geometric inference.

Key Features:
- Entity Registry: Tracks all topology entities with UUIDs
- Tagged Creation: Automatically tags ed

ges/faces during feature execution
- 4-Tier Resolution: ID → Feature → Role → Geometric fallback
- Regeneration Safety: Same graph = same entity selection

Author: OrionFlow Phase 2
"""
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any, Union
from uuid import uuid4

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
from app.domain.topology_identity import (
    EntityIdentity, EntityRegistry,
    infer_edge_role, infer_edge_axis
)
from app.compilers.v1.errors import SketchCompilationError, FeatureCompilationError
from app.compilers.build123d_compiler_v2 import Build123dCompilerV2

logger = logging.getLogger(__name__)


class CompilationContext:
    """
    Extended compilation context with entity tracking.
    
    Stores both the geometry and entity metadata registry.
    """
    def __init__(self, graph: FeatureGraphV2):
        self.graph = graph
        self.registry = EntityRegistry()
        self.edge_map: Dict[str, Edge] = {}  # entity_id -> Edge
        self.face_map: Dict[str, Face] = {}  # entity_id -> Face
        self.sketches: Dict[str, Any] = {}  # sketch_id -> Sketch


class Build123dCompilerV3(Build123dCompilerV2):
    """
    V3 Compiler with topological identity tracking.
    
    Replaces geometric guessing with explicit entity metadata:
    - Every edge/face gets a UUID and semantic tags
    - Selection uses 4-tier resolution order
    - Regeneration targets same entities across parameter changes
    
    Example:
        ```python
        compiler = Build123dCompilerV3(output_dir=Path("outputs"))
        step, stl, glb, trace = compiler.compile(feature_graph, job_id="xyz")
        
        # Entity registry available in trace
        registry = trace.metadata.get("entity_registry")
        ```
    """
    
    def __init__(self, output_dir: Path = Path("outputs")):
        """Initialize V3 compiler with output directory and validators."""
        super().__init__(output_dir)
        
        # Phase 3: Register geometry validators
        from app.compilers.validators.zero_thickness import ZeroThicknessValidator
        from app.compilers.validators.fillet_validator import FilletValidator
        from app.compilers.validators.self_intersection import SelfIntersectionValidator
        from app.compilers.validators.degenerate_face import DegenerateFaceValidator
        
        self.validators = [
            ZeroThicknessValidator(),
            FilletValidator(),
            SelfIntersectionValidator(),
            DegenerateFaceValidator()
        ]
        
        logger.info(f"Build123dCompilerV3 initialized with {len(self.validators)} validators")
    
    def compile(
        self,
        feature_graph: FeatureGraphV2,
        job_id: str
    ) -> Tuple[Path, Path, Path, ExecutionTrace]:
        """
        Compile FeatureGraphV2 to geometry with entity tracking.
        
        Args:
            feature_graph: Validated FeatureGraphV2 instance
            job_id: Unique identifier for output files
            
        Returns:
            Tuple of (step_path, stl_path, glb_path, execution_trace)
            
        Note:
            Entity registry is stored in trace.metadata["entity_registry"]
        """
        events = []
        ctx = CompilationContext(feature_graph)
        
        try:
            # Phase 1: Compile sketches (inherited from V2)
            for sketch_def in feature_graph.sketches:
                events.append(TraceEvent(
                    stage="sketch_compile",
                    target=sketch_def.id,
                    status="pending"
                ))
                
                try:
                    sketch = self._compile_sketch(sketch_def, feature_graph)
                    ctx.sketches[sketch_def.id] = sketch
                    events[-1].status = "success"
                except Exception as e:
                    events[-1].status = "failure"
                    events[-1].message = str(e)
                    raise SketchCompilationError(f"Sketch '{sketch_def.id}': {e}")
            
            # Phase 2: Apply features with entity tracking
            solid = None
            
            for feature in feature_graph.features:
                events.append(TraceEvent(
                    stage=f"feature_{feature.type}",
                    target=feature.id,
                    status="pending"
                ))
                
                try:
                    solid = self._apply_feature_v3(feature, ctx, solid)
                    events[-1].status = "success"
                    events[-1].message = f"Created {len(ctx.registry.feature_map.get(feature.id, []))} entities"
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
            
            # Store entity registry in trace
            trace = ExecutionTrace(
                success=True,
                events=events,
                retryable=False,
                metadata={
                    "entity_registry": ctx.registry.model_dump(),
                    "entity_count": len(ctx.registry.entities)
                }
            )
            return step_path, stl_path, glb_path, trace
            
        except FeatureCompilationError as e:
            logger.error(f"V3 Compilation failed: {e}")
            
            # Store structured error in trace metadata if available
            metadata = {}
            if hasattr(e, 'compiler_error') and e.compiler_error:
                metadata["compiler_error"] = e.compiler_error.model_dump()
                logger.info(f"Structured error available: {e.compiler_error.error_type}")
            
            trace = ExecutionTrace(
                success=False,
                events=events,
                retryable=True,
                metadata=metadata
            )
            raise
        except Exception as e:
            logger.error(f"V3 Compilation failed: {e}")
            trace = ExecutionTrace(success=False, events=events, retryable=True)
            raise
    
    def _apply_feature_v3(
        self,
        feature: FeatureV2,
        ctx: CompilationContext,
        current_solid: Optional[Solid]
    ) -> Solid:
        """
        Apply a feature with entity tracking and validation.
        
        Phase 3: Includes geometry validation passes after build.
        """
        # Step 1: Build geometry
        if feature.type == "extrude":
            solid = self._apply_extrude_v3(feature, ctx, current_solid)
        elif feature.type == "fillet":
            solid = self._apply_fillet_v3(feature, ctx, current_solid)
        elif feature.type == "chamfer":
            solid = self._apply_chamfer_v3(feature, ctx, current_solid)
        else:
            # Fallback to V2 implementation
            logger.warning(f"Feature type '{feature.type}' not yet V3-enabled, using V2")
            solid = self._apply_feature_v2(feature, ctx.sketches, ctx.graph, current_solid)
        
        # Step 2: VALIDATE geometry (Phase 3)
        self._validate_geometry(solid, feature)
        
        return solid
    
    def _validate_geometry(self, solid: Solid, feature: FeatureV2) -> None:
        """
        Run all geometry validators on the current solid.
        
        Fails fast on first error detected.
        
        Args:
            solid: Geometry to validate
            feature: Feature that created/modified the geometry
            
        Raises:
            FeatureCompilationError: If any validator detects an issue
        """
        for validator in self.validators:
            error = validator.validate(solid, feature)
            if error:
                logger.error(f"{validator.name} failed: {error.reason}")
                # Fail fast with structured error
                raise FeatureCompilationError(
                    error.to_trace_message(),
                    compiler_error=error
                )
    
    def _apply_extrude_v3(
        self,
        feature: FeatureV2,
        ctx: CompilationContext,
        current_solid: Optional[Solid]
    ) -> Solid:
        """Apply extrude feature with edge tagging."""
        sketch_id = feature.sketch
        if sketch_id not in ctx.sketches:
            raise FeatureCompilationError(f"Sketch '{sketch_id}' not found")
        
        depth = self._resolve_param(
            feature.params.get("depth") or feature.params.get("distance"),
            ctx.graph
        )
        
        # Create geometry
        sketch_builder = ctx.sketches[sketch_id]
        target_geo = sketch_builder.sketch if hasattr(sketch_builder, "sketch") else sketch_builder
        new_solid = extrude(target_geo, amount=depth)
        
        # Tag all edges created by this extrude
        self._tag_solid_entities(new_solid, feature, ctx)
        
        # Combine with existing solid
        if current_solid is None:
            return new_solid
        else:
            combined = current_solid + new_solid
            # Re-tag combined solid (topology may have changed)
            self._tag_solid_entities(combined, feature, ctx)
            return combined
    
    def _apply_fillet_v3(
        self,
        feature: FeatureV2,
        ctx: CompilationContext,
        current_solid: Optional[Solid]
    ) -> Solid:
        """Apply fillet with deterministic edge selection."""
        if current_solid is None:
            raise FeatureCompilationError("Fillet requires existing geometry")
        
        radius = self._resolve_param(feature.params.get("radius"), ctx.graph)
        
        # Use V3 resolution to select edges
        edges = self._resolve_semantic_selector_v3(
            feature.topology_refs,
            current_solid,
            ctx
        )
        
        if not edges:
            logger.warning(f"No edges selected for fillet '{feature.id}', using all edges")
            edges = list(current_solid.edges())
        
        logger.info(f"Fillet '{feature.id}' targeting {len(edges)} edges (V3 selection)")
        
        # Apply fillet
        filleted_solid = fillet(edges, radius=radius)
        
        # Re-tag (fillet creates new edges)
        self._tag_solid_entities(filleted_solid, feature, ctx)
        
        return filleted_solid
    
    def _apply_chamfer_v3(
        self,
        feature: FeatureV2,
        ctx: CompilationContext,
        current_solid: Optional[Solid]
    ) -> Solid:
        """Apply chamfer with deterministic edge selection."""
        if current_solid is None:
            raise FeatureCompilationError("Chamfer requires existing geometry")
        
        distance = self._resolve_param(feature.params.get("distance"), ctx.graph)
        
        edges = self._resolve_semantic_selector_v3(
            feature.topology_refs,
            current_solid,
            ctx
        )
        
        if not edges:
            edges = list(current_solid.edges())
        
        chamfered_solid = chamfer(edges, length=distance)
        self._tag_solid_entities(chamfered_solid, feature, ctx)
        
        return chamfered_solid
    
    def _tag_solid_entities(
        self,
        solid: Solid,
        feature: FeatureV2,
        ctx: CompilationContext
    ) -> None:
        """
        Tag all edges/faces in a solid with entity metadata.
        
        This is called after every feature operation to maintain the registry.
        """
        for edge in solid.edges():
            # Check if already tagged (avoid duplicates)
            existing_id = self._find_edge_id(edge, ctx)
            if existing_id:
                continue  # Already tracked
            
            # Create new identity
            role = infer_edge_role(edge, feature.type, feature.params)
            axis = infer_edge_axis(edge)
            
            identity = EntityIdentity(
                created_by=feature.id,
                role=role,
                axis=axis,
                feature_type=feature.type
            )
            
            entity_id = ctx.registry.register(identity)
            ctx.edge_map[entity_id] = edge
            
        # Tag faces (future enhancement)
        # for face in solid.faces():
        #     ...
    
    def _find_edge_id(self, edge: Edge, ctx: CompilationContext) -> Optional[str]:
        """Find entity ID for an existing edge (by geometric equivalence)."""
        # Quick geometric hash check
        center = edge.center()
        length = edge.length
        
        for eid, existing_edge in ctx.edge_map.items():
            try:
                if (abs(existing_edge.center().X - center.X) < 0.001 and
                    abs(existing_edge.center().Y - center.Y) < 0.001 and
                    abs(existing_edge.center().Z - center.Z) < 0.001 and
                    abs(existing_edge.length - length) < 0.001):
                    return eid
            except:
                continue
        
        return None
    
    def _resolve_semantic_selector_v3(
        self,
        topology_refs: Optional[Dict[str, SemanticSelector]],
        solid: Solid,
        ctx: CompilationContext
    ) -> List[Edge]:
        """
        4-Tier resolution order for semantic selection.
        
        Tier 1: Explicit entity IDs (highest priority)
        Tier 2: Feature origin (created_by)
        Tier 3: Semantic roles (role tags)
        Tier 4: Geometric fallback (V2 logic)
        
        Args:
            topology_refs: Topology reference selectors
            solid: Current solid geometry
            ctx: Compilation context with entity registry
            
        Returns:
            List of selected edges
        """
        if not topology_refs:
            return []
        
        # Look for edge selector
        selector = None
        for key in ["edges", "target_edges", "edge_selector"]:
            if key in topology_refs:
                selector = topology_refs[key]
                break
        
        if not selector:
            return []
        
        # Handle dict conversion
        if isinstance(selector, dict):
            selector = SemanticSelector(**selector)
        
        # TIER 1: Explicit entity IDs
        if selector.entity_ids:
            logger.info(f"V3: Using explicit entity IDs (Tier 1): {selector.entity_ids}")
            edges = []
            for eid in selector.entity_ids:
                if eid in ctx.edge_map:
                    edges.append(ctx.edge_map[eid])
                else:
                    logger.warning(f"Entity ID '{eid}' not found in registry")
            if edges:
                return edges
        
        # TIER 2: Feature origin
        if selector.created_by_feature:
            logger.info(f"V3: Selecting by feature origin (Tier 2): {selector.created_by_feature}")
            identities = ctx.registry.get_by_feature(selector.created_by_feature)
            edges = [ctx.edge_map[identity.id] for identity in identities 
                    if identity.id in ctx.edge_map]
            if edges:
                return edges
        
        # TIER 3: Semantic roles
        if selector.semantic_roles:
            logger.info(f"V3: Selecting by semantic roles (Tier 3): {selector.semantic_roles}")
            all_edges = []
            for role in selector.semantic_roles:
                identities = ctx.registry.get_by_role(role)
                all_edges.extend([ctx.edge_map[identity.id] for identity in identities 
                                if identity.id in ctx.edge_map])
            if all_edges:
                return all_edges
        
        # TIER 4: Geometric fallback (V2 logic)
        logger.warning("V3: Falling back to geometric selection (Tier 4) - non-deterministic!")
        return super()._resolve_semantic_selector(selector, solid, ctx.graph)
