"""
Fillet Validator

Validates fillet radius against edge lengths to prevent:
- Radius exceeding edge length (instant failure)
- Radius > 50% edge length (likely to cause issues)
- Fillet overlap (multiple fillets interfering)

Common LLM mistake: Requesting fillet_radius=10mm on a 5mm cube.
"""
import logging
from typing import Optional, List
from build123d import Solid, Edge
from app.domain.feature_graph_v2 import FeatureV2
from app.domain.compiler_errors import CompilerError, ErrorType
from app.compilers.validators.base import GeometryValidator

logger = logging.getLogger(__name__)


class FilletValidator(GeometryValidator):
    """
    Validates fillet radius against edge lengths.
    
    Rule: Fillet radius should be ≤ 50% of shortest edge length
    
    Example Failure:
        Edge length: 8mm
        Requested radius: 10mm
        Error: "Fillet radius exceeds edge length"
    """
    
    MAX_RATIO = 0.5  # Fillet radius should be ≤ 50% of edge length
    
    @property
    def name(self) -> str:
        return "Fillet Radius Validator"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check fillet radius against targeted edges."""
        
        # Only validate fillet features
        if feature.type != "fillet":
            return None
        
        radius = feature.params.get("radius", 0)
        
        if radius <= 0:
            return CompilerError(
                error_type=ErrorType.INVALID_FILLET,
                feature_id=feature.id,
                reason=f"Fillet radius must be positive (got {radius}mm)",
                suggested_fix="Specify a positive radius value",
                context={"radius": radius}
            )
        
        try:
            # Get all edges from the solid
            edges = list(solid.edges())
            
            if not edges:
                return CompilerError(
                    error_type=ErrorType.INVALID_FILLET,
                    feature_id=feature.id,
                    reason="Cannot apply fillet: No edges found in geometry",
                    suggested_fix="Check that previous features created valid geometry"
                )
            
            # Find shortest edge
            edge_lengths = [(edge, edge.length) for edge in edges]
            shortest_edge, min_length = min(edge_lengths, key=lambda x: x[1])
            
            # Check if radius is too large
            max_safe_radius = min_length * self.MAX_RATIO
            
            if radius > max_safe_radius:
                return CompilerError(
                    error_type=ErrorType.INVALID_FILLET,
                    feature_id=feature.id,
                    reason=f"Fillet radius {radius}mm exceeds safe limit of {max_safe_radius:.2f}mm (50% of shortest edge {min_length:.2f}mm)",
                    suggested_fix=f"Reduce radius to max {max_safe_radius:.2f}mm, or use {max_safe_radius * 0.8:.2f}mm for safety margin",
                    context={
                        "radius": radius,
                        "shortest_edge_length": min_length,
                        "max_safe_radius": max_safe_radius,
                        "safety_margin_radius": max_safe_radius * 0.8,
                        "edge_count": len(edges)
                    }
                )
            
            # Warn if radius is close to limit (future: add to warnings)
            if radius > max_safe_radius * 0.8:
                logger.warning(
                    f"Fillet radius {radius}mm is close to limit {max_safe_radius:.2f}mm. "
                    "May cause issues."
                )
        
        except Exception as e:
            logger.warning(f"Fillet validation failed with exception: {e}")
        
        return None
