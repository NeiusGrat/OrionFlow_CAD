"""
Geometry Metrics Calculator - Compute geometry properties for quality assessment.

==============================================================================
PURPOSE: RL Reward Signals & Quality Filtering
==============================================================================

These metrics enable:
1. RL reward signals (volume > 0, is_manifold = True as positive rewards)
2. Quality filtering for training datasets
3. Manufacturing validation (min thickness, printable bounds)
4. Pre-kernel validation (Step 4 requirement)
"""
from typing import Optional, Dict, Any
import logging

from app.domain.training_sample import GeometryMetrics

logger = logging.getLogger(__name__)


def calculate_geometry_metrics(solid: Any) -> GeometryMetrics:
    """
    Calculate comprehensive geometry metrics from Build123d solid.
    
    Args:
        solid: Build123d Part or Solid object
        
    Returns:
        GeometryMetrics with computed properties
    """
    try:
        # Handle None or invalid input
        if solid is None:
            logger.warning("Cannot calculate metrics: solid is None")
            return GeometryMetrics.empty()
            
        # Check if it's a string (e.g., "onshape_cloud_entity")
        if isinstance(solid, str):
            logger.info(f"Cloud entity detected: {solid}, returning empty metrics")
            return GeometryMetrics.empty()
        
        # =====================================================================
        # Extract Build123d properties
        # =====================================================================
        
        # Volume
        volume = 0.0
        try:
            if hasattr(solid, 'volume'):
                volume = float(solid.volume)
        except Exception as e:
            logger.warning(f"Failed to get volume: {e}")
        
        # Surface area
        surface_area = 0.0
        try:
            if hasattr(solid, 'area'):
                surface_area = float(solid.area)
        except Exception as e:
            logger.warning(f"Failed to get surface area: {e}")
        
        # Bounding box
        bounding_box = {}
        try:
            if hasattr(solid, 'bounding_box'):
                bb = solid.bounding_box()
                if bb:
                    bounding_box = {
                        "x_min": float(bb.min.X),
                        "x_max": float(bb.max.X),
                        "y_min": float(bb.min.Y),
                        "y_max": float(bb.max.Y),
                        "z_min": float(bb.min.Z),
                        "z_max": float(bb.max.Z)
                    }
        except Exception as e:
            logger.warning(f"Failed to get bounding box: {e}")
        
        # Validity check (OpenCASCADE)
        is_valid = False
        try:
            if hasattr(solid, 'is_valid'):
                is_valid = bool(solid.is_valid)
            elif volume > 0:
                # Fallback: assume valid if has volume
                is_valid = True
        except Exception as e:
            logger.warning(f"Failed to check validity: {e}")
        
        # Manifold check (watertight)
        is_manifold = False
        try:
            # Build123d doesn't have direct manifold check
            # Use heuristic: valid solid with volume is likely manifold
            if is_valid and volume > 0:
                is_manifold = True
        except Exception as e:
            logger.warning(f"Failed to check manifold: {e}")
        
        # Face/Edge/Vertex counts
        face_count = 0
        edge_count = 0
        vertex_count = 0
        
        try:
            if hasattr(solid, 'faces'):
                face_count = len(list(solid.faces()))
        except Exception as e:
            logger.warning(f"Failed to count faces: {e}")
            
        try:
            if hasattr(solid, 'edges'):
                edge_count = len(list(solid.edges()))
        except Exception as e:
            logger.warning(f"Failed to count edges: {e}")
            
        try:
            if hasattr(solid, 'vertices'):
                vertex_count = len(list(solid.vertices()))
        except Exception as e:
            logger.warning(f"Failed to count vertices: {e}")
        
        return GeometryMetrics(
            volume=volume,
            surface_area=surface_area,
            bounding_box=bounding_box,
            is_valid=is_valid,
            is_manifold=is_manifold,
            face_count=face_count,
            edge_count=edge_count,
            vertex_count=vertex_count
        )
        
    except Exception as e:
        logger.error(f"Failed to calculate geometry metrics: {e}")
        return GeometryMetrics.empty()


def validate_manufacturing_constraints(
    metrics: GeometryMetrics,
    min_volume: float = 1.0,
    min_dimension: float = 0.5,
    max_dimension: float = 1000.0
) -> Dict[str, Any]:
    """
    Validate geometry against manufacturing constraints.
    
    This is pre-kernel validation (Step 4 requirement) that:
    - Prevents kernel crashes
    - Prevents garbage STEP exports
    - Enables RL reward signals
    
    Args:
        metrics: Calculated geometry metrics
        min_volume: Minimum volume in mm³
        min_dimension: Minimum dimension in mm
        max_dimension: Maximum dimension in mm
        
    Returns:
        Dict with 'valid' bool and 'errors' list
    """
    errors = []
    
    # Check volume
    if metrics.volume < min_volume:
        errors.append(f"Volume {metrics.volume:.2f} mm³ is below minimum {min_volume} mm³")
    
    # Check validity
    if not metrics.is_valid:
        errors.append("Geometry failed OpenCASCADE validity check")
    
    # Check manifold
    if not metrics.is_manifold:
        errors.append("Geometry is not manifold (not watertight)")
    
    # Check bounding box dimensions
    if metrics.bounding_box:
        for axis in ['x', 'y', 'z']:
            min_key = f"{axis}_min"
            max_key = f"{axis}_max"
            if min_key in metrics.bounding_box and max_key in metrics.bounding_box:
                dimension = metrics.bounding_box[max_key] - metrics.bounding_box[min_key]
                
                if dimension < min_dimension:
                    errors.append(
                        f"{axis.upper()} dimension {dimension:.2f}mm is below minimum {min_dimension}mm"
                    )
                if dimension > max_dimension:
                    errors.append(
                        f"{axis.upper()} dimension {dimension:.2f}mm exceeds maximum {max_dimension}mm"
                    )
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }
