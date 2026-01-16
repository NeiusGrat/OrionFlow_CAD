"""
Base Compiler - Abstract base class for CAD compilers.

Provides shared functionality for all compiler implementations:
- Parameter resolution
- File export (STEP, STL, GLB)
- Logging and error handling

All concrete compilers (Build123dCompilerV1/V2/V3, OnshapeCompiler) should inherit from this.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import logging

import trimesh

from app.config import settings
from app.logging_config import get_logger
from app.exceptions import CompilationError, ExportError, GeometryError

logger = get_logger(__name__)


class BuildContext:
    """
    Compilation context managing state during build.
    
    Ensures deterministic ordering and single source of truth for:
    - Parameters (resolved values)
    - Compiled sketches (2D profiles)
    - Current solid body (3D geometry)
    
    Attributes:
        cfg: The FeatureGraph being compiled
        params: Resolved parameter dictionary
        sketches: Map of sketch ID to compiled sketch object
        part: Current 3D solid body
    """
    
    def __init__(self, cfg):
        """
        Initialize build context from FeatureGraph.
        
        Args:
            cfg: FeatureGraph to compile
        """
        self.cfg = cfg
        self.params: Dict[str, float] = dict(cfg.parameters)
        self.sketches: Dict[str, Any] = {}
        self.part: Any = None


class BaseCompiler(ABC):
    """
    Abstract base class for CAD compilers.
    
    Provides:
    - Common export functionality (STEP, STL, GLB)
    - Parameter resolution
    - Consistent error handling
    - Logging integration
    
    Subclasses must implement:
    - compile(): Main compilation entry point
    - _build_geometry(): Build 3D geometry from CFG
    """
    
    # Export quality settings (can be overridden by subclasses)
    STL_LINEAR_DEFLECTION = 0.05  # mm - smaller = higher quality
    STL_ANGULAR_DEFLECTION = 0.5  # degrees
    
    def __init__(self, output_dir: Path = None):
        """
        Initialize compiler.
        
        Args:
            output_dir: Directory for output files (defaults to settings.output_dir)
        """
        self.output_dir = output_dir or settings.output_dir
        self.output_dir.mkdir(exist_ok=True, parents=True)
        logger.debug("compiler_initialized", output_dir=str(self.output_dir))
    
    @abstractmethod
    def compile(self, cfg, job_id: str) -> Dict[str, Path]:
        """
        Compile FeatureGraph to geometry files.
        
        Args:
            cfg: FeatureGraph to compile
            job_id: Unique job identifier for output files
            
        Returns:
            Dictionary with keys 'step', 'stl', 'glb' and Path values
            
        Raises:
            CompilationError: If compilation fails
        """
        pass
    
    @abstractmethod
    def _build_geometry(self, ctx: BuildContext) -> Any:
        """
        Build 3D geometry from FeatureGraph.
        
        Args:
            ctx: Build context with cfg and state
            
        Returns:
            Compiled solid/part object
            
        Raises:
            CompilationError: If geometry construction fails
        """
        pass
    
    def _resolve_param(self, ctx: BuildContext, raw_value: Any) -> float:
        """
        Resolve parameter value from string ('$param') or literal.
        
        Handles:
        - Direct float/int values
        - Parameter references ('$width')
        - String representations of numbers
        
        Args:
            ctx: Build context with parameter dictionary
            raw_value: Raw value from FeatureGraph
            
        Returns:
            Resolved float value
            
        Raises:
            CompilationError: If parameter reference is unknown
        """
        if raw_value is None:
            return 0.0
            
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        
        if isinstance(raw_value, str) and raw_value.startswith("$"):
            param_name = raw_value[1:]
            if param_name not in ctx.params:
                raise CompilationError(
                    message=f"Unknown parameter reference: {raw_value}",
                    failed_feature=None
                )
            return float(ctx.params[param_name])
        
        try:
            return float(raw_value)
        except (ValueError, TypeError):
            logger.warning("param_resolution_failed", raw_value=raw_value)
            return 0.0
    
    def _export_geometry(
        self, 
        part: Any, 
        job_id: str,
        export_step_fn,
        export_stl_fn
    ) -> Dict[str, Path]:
        """
        Export compiled geometry to STEP, STL, and GLB files.
        
        Args:
            part: Compiled solid/part object
            job_id: Job identifier for filenames
            export_step_fn: Function to export STEP (callable(part, path))
            export_stl_fn: Function to export STL (callable(part, path, tolerance, angular_tolerance))
            
        Returns:
            Dictionary with 'step', 'stl', 'glb' paths
            
        Raises:
            ExportError: If export fails
        """
        step_path = self.output_dir / f"{job_id}.step"
        stl_path = self.output_dir / f"{job_id}.stl"
        glb_path = self.output_dir / f"{job_id}.glb"
        
        try:
            # Export STEP (exact B-Rep)
            logger.debug("exporting_step", path=str(step_path))
            export_step_fn(part, str(step_path))
            
            # Export STL (tessellated mesh)
            logger.debug("exporting_stl", path=str(stl_path))
            export_stl_fn(
                part,
                str(stl_path),
                tolerance=self.STL_LINEAR_DEFLECTION,
                angular_tolerance=self.STL_ANGULAR_DEFLECTION
            )
            
            # Convert STL to GLB for web
            logger.debug("converting_to_glb", path=str(glb_path))
            self._convert_to_glb(stl_path, glb_path)
            
            logger.info(
                "export_complete",
                job_id=job_id,
                step_size=step_path.stat().st_size,
                stl_size=stl_path.stat().st_size,
                glb_size=glb_path.stat().st_size
            )
            
            return {
                "step": step_path,
                "stl": stl_path,
                "glb": glb_path
            }
            
        except Exception as e:
            logger.error("export_failed", job_id=job_id, error=str(e))
            raise ExportError(
                message=f"Export failed: {e}",
                file_path=str(self.output_dir / job_id),
                format="multi"
            ) from e
    
    @staticmethod
    def _convert_to_glb(stl_path: Path, glb_path: Path) -> None:
        """
        Convert STL mesh to GLB format for web viewing.
        
        Uses trimesh for conversion.
        
        Args:
            stl_path: Path to source STL file
            glb_path: Path to write GLB file
            
        Raises:
            ExportError: If conversion fails
        """
        try:
            mesh = trimesh.load_mesh(str(stl_path))
            glb_bytes = mesh.export(file_type="glb")
            glb_path.write_bytes(glb_bytes)
        except Exception as e:
            logger.error("glb_conversion_failed", error=str(e))
            raise ExportError(
                message=f"GLB conversion failed: {e}",
                file_path=str(glb_path),
                format="glb"
            ) from e
    
    def _validate_cfg(self, cfg) -> None:
        """
        Validate FeatureGraph before compilation.
        
        Override in subclasses for version-specific validation.
        
        Args:
            cfg: FeatureGraph to validate
            
        Raises:
            CompilationError: If validation fails
        """
        if not cfg.sketches and not cfg.features:
            raise CompilationError(
                message="FeatureGraph has no sketches or features",
                failed_feature=None
            )
