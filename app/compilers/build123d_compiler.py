"""
Build123d Compiler - FeatureGraph v1 → STEP/STL/GLB

Deterministically compiles the Canonical Feature Graph (CFG) into manufacturing artifacts.
- STEP: Exact B-Rep for manufacturing
- STL: Tessellated mesh for printing/rendering
- GLB: Web-ready preview

Architecture:
    FeatureGraph → BuildContext → Solid → Export
"""
from pathlib import Path
from typing import Tuple, Dict, Any, List
import logging
import trimesh
from build123d import *

from app.domain.feature_graph import FeatureGraph, Sketch, Feature

logger = logging.getLogger(__name__)


class CompilationError(Exception):
    """Raised when compilation fails."""
    pass


class BuildContext:
    """
    Compilation context managing state during build.
    Ensures deterministic ordering and single source of truth.
    """
    def __init__(self, cfg: FeatureGraph):
        self.cfg = cfg
        self.params: Dict[str, float] = cfg.parameters
        self.sketches: Dict[str, Sketch] = {}  # Map id -> Build123d Sketch object
        self.part: Part = None  # Current solid body


class Build123dCompiler:
    """
    Compiles FeatureGraph v1 to geometry.
    
    Principles:
    - Deterministic: Output depends strictly on input graph
    - Parametric: Dimensions resolved from cfg.parameters
    - Safe: No code execution, purely declarative
    """
    
    # Export settings
    STL_LINEAR_DEFLECTION = 0.05  # mm
    STL_ANGULAR_DEFLECTION = 0.5  # degrees
    
    def __init__(self, output_dir: Path = Path("outputs")):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True, parents=True)
    
    def compile(self, cfg: FeatureGraph, job_id: str) -> Tuple[Path, Path, Path]:
        """
        Main entry point.
        
        Args:
            cfg: Canonical Feature Graph
            job_id: Unique job identifier
            
        Returns:
            (step_path, stl_path, glb_path)
        """
        logger.info(f"Compiling job_id={job_id} (CFG v1)")
        
        try:
            # 1. Initialize context
            ctx = BuildContext(cfg)
            
            # 2. Build geometry
            self._build_geometry(ctx)
            
            if ctx.part is None:
                raise CompilationError("Build resulted in empty part")
            
            # 3. Export artifacts
            step_path = self.output_dir / f"{job_id}.step"
            stl_path = self.output_dir / f"{job_id}.stl"
            glb_path = self.output_dir / f"{job_id}.glb"
            
            # Export STEP (Exact B-Rep)
            ctx.part.export_step(str(step_path))
            
            # Export STL (Tessellated)
            ctx.part.export_stl(
                str(stl_path),
                linear_deflection=self.STL_LINEAR_DEFLECTION,
                angular_deflection=self.STL_ANGULAR_DEFLECTION
            )
            
            # Convert to GLB for web
            self._convert_to_glb(stl_path, glb_path)
            
            return step_path, stl_path, glb_path
            
        except Exception as e:
            logger.error(f"Compilation failed: {e}")
            raise CompilationError(f"Build failed: {e}") from e

    def _build_geometry(self, ctx: BuildContext):
        """Execute the build pipeline."""
        
        # 1. Compile all Sketches first (order independent in v1 for now)
        for sketch_def in ctx.cfg.sketches:
            self._compile_sketch(ctx, sketch_def)
            
        # 2. Compile Features in order (history-based)
        for feature in ctx.cfg.features:
            self._compile_feature(ctx, feature)

    def _compile_sketch(self, ctx: BuildContext, sketch_def: Sketch):
        """Compile a 2D sketch."""
        plane = Plane.XY if sketch_def.plane == "XY" \
           else Plane.YZ if sketch_def.plane == "YZ" \
           else Plane.XZ
           
        with BuildSketch(plane) as s:
            for entity in sketch_def.entities:
                self._compile_sketch_entity(ctx, entity)
        
        ctx.sketches[sketch_def.id] = s

    def _compile_sketch_entity(self, ctx: BuildContext, entity):
        """Compile a single sketch entity."""
        # Helper to resolve params: "$p" -> value, "10" -> 10.0
        def val(k): 
            raw = entity.params.get(k)
            return self._resolve_param(ctx, raw)

        if entity.type == "rectangle":
            # Center defaults to (0,0) if not specified
            # Build123d Rectangle is centered by default
            Rectangle(width=val("width"), height=val("height"))
            
        elif entity.type == "circle":
            Circle(radius=val("radius"))
            
        elif entity.type == "line":
            # Line((x1,y1), (x2,y2))
            # Requires parsing list/tuple params if passed as strings
            pass # TODO: Implement line parsing if needed
            
        elif entity.type == "polygon":
            RegularPolygon(radius=val("radius"), side_count=int(val("sides")))

    def _compile_feature(self, ctx: BuildContext, feature: Feature):
        """Apply a 3D feature operation."""
        
        # Resolve common parameters
        def val(k): return self._resolve_param(ctx, feature.params.get(k))
        
        if feature.type == "extrude":
            if not feature.sketch:
                raise CompilationError(f"Extrude feature '{feature.id}' missing sketch reference")
            
            # Retrieve compiled sketch
            # build123d Sketch object is context manager, but we need the underlying object
            # context.sketches actually stores the BuildSketch context? 
            # No, we need to add the sketch to the part.
            
            target_sketch = ctx.sketches.get(feature.sketch)
            if not target_sketch:
                raise CompilationError(f"Sketch '{feature.sketch}' not found")

            # Operation: Add to part
            # Logic: If solid exists, add/cut. If not, create.
            
            with BuildPart() as p:
                # If we have existing geometry, we might need to add it?
                # Build123d approach: pending changes are applied.
                # Simplest for v1: Use explicit operations on ctx.part
                
                # New approach:
                # 1. Bring existing part into context (if any)
                if ctx.part:
                    add(ctx.part)
                
                # 2. Add sketch
                add(target_sketch)
                
                # 3. Extrude
                extrude(amount=val("depth"))
            
            ctx.part = p.part

        elif feature.type == "cut":
            if not feature.sketch:
                 raise CompilationError(f"Cut feature '{feature.id}' missing sketch")
            target_sketch = ctx.sketches.get(feature.sketch)
            
            with BuildPart() as p:
                if ctx.part: add(ctx.part)
                add(target_sketch)
                extrude(amount=val("depth"), mode=Mode.SUBTRACT)
            ctx.part = p.part

        elif feature.type == "fillet":
            if not ctx.part:
                raise CompilationError("Cannot fillet: no part exists")
                
            radius = val("radius")
            
            # Naive selection: Fillet ALL edges (v1 simplification)
            # Future: specialized selectors via metadata
            with BuildPart() as p:
                add(ctx.part)
                fillet(p.edges(), radius=radius)
            ctx.part = p.part
            
        elif feature.type == "chamfer":
            if not ctx.part: raise CompilationError("Cannot chamfer: no part")
            dist = val("distance")
            with BuildPart() as p:
                add(ctx.part)
                chamfer(p.edges(), length=dist)
            ctx.part = p.part

    def _resolve_param(self, ctx: BuildContext, raw_value: Any) -> float:
        """Resolve parameter value from string ('$param') or float."""
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        
        if isinstance(raw_value, str) and raw_value.startswith("$"):
            param_name = raw_value[1:]
            if param_name not in ctx.params:
                # Fallback or error?
                # Try explicit param dictionary lookup
                # The CFG v1 schema says params is Dict[str, float]
                # But inputs might be "$length"
                raise CompilationError(f"Unknown parameter reference: {raw_value}")
            return float(ctx.params[param_name])
            
        try:
            return float(raw_value)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _convert_to_glb(stl_path: Path, glb_path: Path):
        """Convert STL to GLB for web viewer."""
        try:
           mesh = trimesh.load_mesh(str(stl_path))
           glb_bytes = mesh.export(file_type="glb")
           glb_path.write_bytes(glb_bytes)
        except Exception as e:
            logger.error(f"GLB conversion failed: {e}")
