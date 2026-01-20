"""
Zero-Thickness Validator

Detects extrusions with near-zero depth that produce degenerate geometry.

Common causes:
- User specified depth = 0
- Parameter resolved to very small value (e.g., $depth where depth = 0.001)
- LLM hallucinated unrealistic dimensions
"""
import logging
from typing import Optional
from build123d import Solid
from app.domain.feature_graph_v2 import FeatureV2
from app.domain.compiler_errors import CompilerError, ErrorType
from app.compilers.validators.base import GeometryValidator

logger = logging.getLogger(__name__)


class ZeroThicknessValidator(GeometryValidator):
    """
    Detects extrusions with near-zero depth.
    
    Threshold: 0.01mm (anything smaller is likely a mistake)
    
    Example Failure:
        Feature: extrude(depth=0.001)
        Error: "Extrude depth 0.001mm is too small (< 0.01mm)"
    """
    
    THRESHOLD = 0.01  # mm - minimum acceptable dimension
    
    @property
    def name(self) -> str:
        return "Zero-Thickness Detector"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check if extrude depth is below threshold."""
        
        # Only validate extrude features
        if feature.type != "extrude":
            return None
        
        try:
            # Get bounding box
            bbox = solid.bounding_box()
            
            # Check all dimensions
            dimensions = {
                "X": bbox.size.X,
                "Y": bbox.size.Y,
                "Z": bbox.size.Z
            }
            
            min_dimension = min(dimensions.values())
            min_axis = min(dimensions, key=dimensions.get)
            
            if min_dimension < self.THRESHOLD:
                depth_param = feature.params.get("depth") or feature.params.get("distance", 0)
                
                return CompilerError(
                    error_type=ErrorType.ZERO_THICKNESS,
                    feature_id=feature.id,
                    reason=f"Extrude results in {min_axis}-dimension of {min_dimension:.4f}mm (< {self.THRESHOLD}mm threshold)",
                    suggested_fix=f"Increase extrude depth to at least {self.THRESHOLD}mm",
                    context={
                        "depth_parameter": depth_param,
                        "resulting_dimensions": dimensions,
                        "min_dimension": min_dimension,
                        "threshold": self.THRESHOLD
                    }
                )
        
        except Exception as e:
            # Geometry might be invalid in other ways
            # Don't fail validation, let other validators catch it
            logger.warning(f"Zero-thickness check failed with exception: {e}")
        
        return None
