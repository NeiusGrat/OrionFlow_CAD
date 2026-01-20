"""
Manufacturing Validators - Phase 5

Production-focused validators that enforce manufacturing constraints:
- CNC tool diameter limits
- Hole size standards
- Wall thickness rules
- Process-specific geometry checks

These extend the Phase 3 geometry validators with manufacturing intelligence.
"""
import logging
from typing import Optional
from build123d import Solid
from app.domain.feature_graph_v2 import FeatureV2
from app.domain.compiler_errors import CompilerError, ErrorType
from app.compilers.validators.base import GeometryValidator
from app.domain.manufacturing import ManufacturingConstraints

logger = logging.getLogger(__name__)


class CNCFilletValidator(GeometryValidator):
    """
    Enforce CNC-compatible fillet radii.
    
    Rule: Fillet radius must be ≥ tool_diameter / 2
    
    Example:
        6mm end mill → min 3mm fillet radius
    """
    
    def __init__(self, constraints: ManufacturingConstraints):
        self.constraints = constraints
    
    @property
    def name(self) -> str:
        return "CNC Fillet Validator"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check fillet radius against CNC tool size."""
        
        if feature.type != "fillet":
            return None
        
        if not self.constraints.min_fillet_radius:
            return None  # No constraint set
        
        radius = feature.params.get("radius", 0)
        
        # Skip validation if parameter is not a number
        if isinstance(radius, str):
            return None
        
        min_radius = self.constraints.min_fillet_radius
        
        if radius < min_radius:
            tool_dia = self.constraints.min_tool_diameter or (min_radius * 2)
            
            return CompilerError(
                error_type=ErrorType.INVALID_FILLET,
                feature_id=feature.id,
                reason=f"Fillet radius {radius}mm < CNC minimum {min_radius}mm (tool diameter {tool_dia}mm)",
                suggested_fix=f"Increase radius to {min_radius}mm or use smaller tool",
                context={
                    "radius": radius,
                    "min_cnc_radius": min_radius,
                    "tool_diameter": tool_dia,
                    "manufacturing_process": self.constraints.process
                }
            )
        
        return None


class WallThicknessValidator(GeometryValidator):
    """
    Enforce minimum wall thickness for manufacturing process.
    
    Rules vary by process:
    - CNC: 2mm minimum (rigidity, tool deflection)
    - 3D print: 2x nozzle diameter (2 perimeters)
    - Casting: 4mm minimum (avoid shrinkage defects)
    """
    
    def __init__(self, constraints: ManufacturingConstraints):
        self.constraints = constraints
    
    @property
    def name(self) -> str:
        return "Wall Thickness Validator"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check wall thickness against process minimum."""
        
        # Check shell/extrude depth
        if feature.type == "extrude":
            depth = feature.params.get("depth") or feature.params.get("distance", 0)
            
            # Skip validation if parameter is not a number
            if isinstance(depth, str):
                return None
            
            if self.constraints.min_wall_thickness and depth < self.constraints.min_wall_thickness:
                return CompilerError(
                    error_type=ErrorType.ZERO_THICKNESS,
                    feature_id=feature.id,
                    reason=f"Extrude depth {depth}mm < minimum wall thickness {self.constraints.min_wall_thickness}mm for {self.constraints.process}",
                    suggested_fix=f"Increase depth to {self.constraints.min_wall_thickness}mm",
                    context={
                        "depth": depth,
                        "min_thickness": self.constraints.min_wall_thickness,
                        "process": self.constraints.process
                    }
                )
        
        elif feature.type == "shell":
            thickness = feature.params.get("thickness", 0)
            
            # Skip validation if parameter is not a number
            if isinstance(thickness, str):
                return None
            
            if self.constraints.min_wall_thickness and thickness < self.constraints.min_wall_thickness:
                return CompilerError(
                    error_type=ErrorType.INVALID_PARAMETER,
                    feature_id=feature.id,
                    reason=f"Shell thickness {thickness}mm < minimum {self.constraints.min_wall_thickness}mm",
                    suggested_fix=f"Increase to {self.constraints.min_wall_thickness}mm",
                    context={
                        "thickness": thickness,
                        "min_thickness": self.constraints.min_wall_thickness
                    }
                )
        
        return None


class HoleStandardsValidator(GeometryValidator):
    """
    Recommend standard hole sizes for easier sourcing.
    
    Standards:
    - ISO Metric: 2.5, 3, 4, 5, 6, 8, 10, 12mm
    - ANSI Inch: #10 (4.8mm), 1/4" (6.35mm), etc.
    
    Non-standard holes require custom tooling (costly).
    """
    
    def __init__(self, constraints: ManufacturingConstraints):
        self.constraints = constraints
    
    @property
    def name(self) -> str:
        return "Hole Standards Checker"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check hole diameter against standards."""
        
        if feature.type != "hole":
            return None  # Not a hole feature
        
        diameter = feature.params.get("diameter")
        
        # Skip validation if parameter is not a number
        if isinstance(diameter, str):
            return None
            
        if not diameter:
            return None
        
        standard_sizes = self.constraints.standard_hole_sizes
        if not standard_sizes:
            return None
        
        # Find nearest standard
        nearest = min(standard_sizes, key=lambda s: abs(s - diameter))
        tolerance = 0.2  # mm - acceptable deviation
        
        if abs(diameter - nearest) > tolerance:
            # Not standard - warning only (not blocking)
            logger.warning(
                f"Hole diameter {diameter}mm not standard. "
                f"Nearest standard: {nearest}mm. "
                f"Non-standard holes may increase cost."
            )
            
            # Return error only if very far from standard
            if abs(diameter - nearest) > 1.0:
                return CompilerError(
                    error_type=ErrorType.MANUFACTURING_VIOLATION,
                    feature_id=feature.id,
                    reason=f"Hole diameter {diameter}mm not close to standard sizes",
                    suggested_fix=f"Use standard diameter: {nearest}mm (or {standard_sizes})",
                    context={
                        "diameter": diameter,
                        "nearest_standard": nearest,
                        "all_standards": standard_sizes,
                        "note": "Non-standard holes require custom tooling and increase cost"
                    }
                )
        
        return None


class ToolAccessValidator(GeometryValidator):
    """
    Check if internal features are reachable by tools.
    
    Rules:
    - Pocket depth ≤ 4x tool diameter (deflection)
    - Internal corner radii ≥ tool radius
    - Wall-to-wall clearance ≥ tool diameter
    
    Simplified version for Phase 5.
    """
    
    def __init__(self, constraints: ManufacturingConstraints):
        self.constraints = constraints
    
    @property
    def name(self) -> str:
        return "Tool Access Checker"
    
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """Check tool access for deep pockets."""
        
        # Simplified: check extrude depth vs tool length
        if feature.type == "extrude":
            depth = feature.params.get("depth") or feature.params.get("distance", 0)
            
            # Skip validation if parameter is not a number
            if isinstance(depth, str):
                return None
            
            if self.constraints.max_tool_length and depth > self.constraints.max_tool_length:
                return CompilerError(
                    error_type=ErrorType.MANUFACTURING_VIOLATION,
                    feature_id=feature.id,
                    reason=f"Feature depth {depth}mm exceeds max tool length {self.constraints.max_tool_length}mm",
                    suggested_fix=f"Reduce depth or use longer tool",
                    context={
                        "depth": depth,
                        "max_tool_length": self.constraints.max_tool_length
                    }
                )
        
        return None
