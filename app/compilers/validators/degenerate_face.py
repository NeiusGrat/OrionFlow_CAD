"""
Degenerate Face Validator

Detects faces with near-zero area that indicate geometry failures.

Degenerate faces occur when:
- Extrude depth approaches zero
- Boolean operations partially fail
- Sketch geometry collapses to a line/point

These faces cause export failures and should be caught early.
"""
import logging
from typing import Optional
from build123d import Solid
from app.domain.feature_graph_v2 import FeatureV2
from app.domain.compiler_errors import CompilerError, ErrorType
from app.compilers.validators import GeometryValidator

logger = logging.getLogger(__name__)


class DegenerateFaceValidator(GeometryValidator):
    """
    Detects faces with near-zero area.
    
    Threshold: 0.001 mm² (anything smaller is likely degenerate)
    
    Example Failure:
        Face area: 0.0001 mm²
        Error: "Degenerate face detected"
    """
    
    AREA_THRESHOLD = 0.001  # mm² - minimum acceptable face area
    
    @property
    def name(self) -> str:
        return "Degenerate Face Detector"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check all faces for near-zero area."""
        
        try:
            faces = list(solid.faces())
            
            if not faces:
                # No faces is a problem, but might be caught by other validators
                return CompilerError(
                    error_type=ErrorType.TOPOLOGY_ERROR,
                    feature_id=feature.id,
                    reason="Geometry has no faces (invalid solid)",
                    suggested_fix="Check sketch validity and feature parameters"
                )
            
            # Check each face area
            face_areas = []
            for i, face in enumerate(faces):
                try:
                    area = face.area
                    face_areas.append((i, area))
                    
                    if area < self.AREA_THRESHOLD:
                        return CompilerError(
                            error_type=ErrorType.DEGENERATE_FACE,
                            feature_id=feature.id,
                            reason=f"Face #{i} has area {area:.6f}mm² (< threshold {self.AREA_THRESHOLD}mm²)",
                            suggested_fix="Check sketch dimensions and extrude depth. Ensure all dimensions are > 0.1mm",
                            context={
                                "face_index": i,
                                "face_area": area,
                                "threshold": self.AREA_THRESHOLD,
                                "total_faces": len(faces)
                            }
                        )
                except Exception as e:
                    # Individual face check failed
                    logger.warning(f"Failed to check face #{i}: {e}")
                    continue
            
            # Log face area statistics
            if face_areas:
                min_area = min(area for _, area in face_areas)
                max_area = max(area for _, area in face_areas)
                logger.debug(
                    f"Face areas: min={min_area:.4f}mm², max={max_area:.4f}mm², "
                    f"count={len(face_areas)}"
                )
        
        except Exception as e:
            logger.warning(f"Degenerate face check failed: {e}")
        
        return None
