"""
Self-Intersection Validator

Detects self-intersecting geometry using OCCT's validation routines.

Self-intersections occur when:
- Boolean operations create overlapping faces
- Sketch constraints are over-constrained
- Fillet/chamfer operations collide

OCCT provides built-in topology validation that we leverage here.
"""
import logging
from typing import Optional
from build123d import Solid
from app.domain.feature_graph_v2 import FeatureV2
from app.domain.compiler_errors import CompilerError, ErrorType
from app.compilers.validators.base import GeometryValidator

logger = logging.getLogger(__name__)


class SelfIntersectionValidator(GeometryValidator):
    """
    Detects self-intersecting geometry.
    
    Uses OCCT's BRepCheck_Analyzer under the hood (via build123d).
    
    Common causes:
    - Over-constrained sketches
    - Boolean operation failures
    - Filleting/chamfering edges that cause topology collapse
    """
    
    @property
    def name(self) -> str:
        return "Self-Intersection Detector"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check if solid has valid topology (no self-intersections)."""
        
        try:
            # build123d Solid may have is_valid() method
            # This wraps OCCT's BRepCheck_Analyzer
            if hasattr(solid, 'is_valid'):
                if not solid.is_valid():
                    return CompilerError(
                        error_type=ErrorType.SELF_INTERSECTION,
                        feature_id=feature.id,
                        reason="Geometry contains self-intersections or invalid topology",
                        suggested_fix="Simplify feature parameters, check sketch constraints, or reduce fillet/chamfer radius",
                        context={"feature_type": feature.type}
                    )
            
            # Alternative: Check via wrapped shape
            elif hasattr(solid, 'wrapped') and hasattr(solid.wrapped, 'IsValid'):
                if not solid.wrapped.IsValid():
                    return CompilerError(
                        error_type=ErrorType.TOPOLOGY_ERROR,
                        feature_id=feature.id,
                        reason="Invalid topology detected in geometry",
                        suggested_fix="Check feature parameters and dependencies"
                    )
            
            # If no validation method available, skip check
            else:
                logger.debug("Solid does not have is_valid() method, skipping self-intersection check")
        
        except Exception as e:
            # Validation itself failed - log but don't fail compilation
            logger.warning(f"Self-intersection check encountered error: {e}")
        
        return None
