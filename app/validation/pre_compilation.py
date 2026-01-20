"""
Pre-Compilation Validation - Symbolic & Manufacturing Constraints

==============================================================================
ARCHITECTURE: Validation BEFORE Kernel (not after)
==============================================================================

This module validates FeatureGraphIR BEFORE sending to the compiler.
This prevents:
- Kernel crashes from impossible geometry
- Garbage STEP files
- Wasted computation on invalid inputs
- Enables RL reward signals later

VALIDATION CATEGORIES:
1. PHYSICS: Geometric feasibility (fillet radius < edge length)
2. MANUFACTURING: Producibility (minimum wall thickness)
3. SANITY: Basic validity (positive dimensions)

TIMING: Runs after FeatureGraphIR construction, before compilation.

Version: 1.0
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Validation Result Types
# =============================================================================

class ValidationSeverity(str, Enum):
    """Severity level of validation issue."""
    ERROR = "error"      # Blocks compilation
    WARNING = "warning"  # Proceeds with caution
    INFO = "info"        # Informational only


class ValidationCategory(str, Enum):
    """Category of validation check."""
    PHYSICS = "physics"              # Geometric feasibility
    MANUFACTURING = "manufacturing"  # Producibility constraints
    SANITY = "sanity"               # Basic validity checks
    TOPOLOGY = "topology"           # Dependency/reference validity


@dataclass
class ValidationIssue:
    """A single validation issue found."""
    code: str
    message: str
    severity: ValidationSeverity
    category: ValidationCategory
    feature_id: Optional[str] = None
    param_name: Optional[str] = None
    actual_value: Optional[float] = None
    allowed_range: Optional[Tuple[float, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "feature_id": self.feature_id,
            "param_name": self.param_name,
            "actual_value": self.actual_value,
            "allowed_range": self.allowed_range
        }


@dataclass
class ValidationResult:
    """Result of validation run."""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    def add_issue(self, issue: ValidationIssue) -> None:
        """Add an issue to the result."""
        self.issues.append(issue)
        if issue.severity == ValidationSeverity.ERROR:
            self.errors += 1
            self.is_valid = False
        elif issue.severity == ValidationSeverity.WARNING:
            self.warnings += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "issues": [i.to_dict() for i in self.issues]
        }


# =============================================================================
# Manufacturing Constraints (Configurable)
# =============================================================================

@dataclass
class ManufacturingConstraints:
    """
    Configurable manufacturing constraints.

    These values depend on the target manufacturing process:
    - 3D Printing: More lenient wall thickness
    - CNC Milling: Minimum tool radius affects fillets
    - Casting: Draft angles, uniform thickness
    """
    # Minimum dimensions (mm)
    min_wall_thickness: float = 0.5
    min_hole_diameter: float = 0.5
    min_extrusion_depth: float = 0.01
    min_fillet_radius: float = 0.1
    min_chamfer_distance: float = 0.1

    # Maximum dimensions (mm)
    max_dimension: float = 10000.0

    # Fillet constraint: radius must be less than this fraction of edge
    fillet_edge_ratio: float = 0.5

    # Draft angle for moldability (degrees)
    min_draft_angle: float = 0.0

    @classmethod
    def for_3d_printing(cls) -> "ManufacturingConstraints":
        """Constraints for FDM/SLA 3D printing."""
        return cls(
            min_wall_thickness=0.8,
            min_hole_diameter=0.5,
            min_extrusion_depth=0.1,
            min_fillet_radius=0.2,
            min_chamfer_distance=0.2
        )

    @classmethod
    def for_cnc_milling(cls) -> "ManufacturingConstraints":
        """Constraints for CNC milling (3mm end mill)."""
        return cls(
            min_wall_thickness=1.0,
            min_hole_diameter=3.0,
            min_extrusion_depth=0.5,
            min_fillet_radius=1.5,  # Min tool radius
            min_chamfer_distance=0.5
        )

    @classmethod
    def for_injection_molding(cls) -> "ManufacturingConstraints":
        """Constraints for injection molding."""
        return cls(
            min_wall_thickness=1.0,
            min_hole_diameter=1.0,
            min_extrusion_depth=0.5,
            min_fillet_radius=0.5,
            min_chamfer_distance=0.3,
            min_draft_angle=1.0  # 1 degree draft
        )


# =============================================================================
# Validation Rules
# =============================================================================

class ValidationRule:
    """Base class for validation rules."""

    code: str = "UNKNOWN"
    category: ValidationCategory = ValidationCategory.SANITY

    def validate(
        self,
        ir: Any,
        constraints: ManufacturingConstraints
    ) -> List[ValidationIssue]:
        """
        Run validation.

        Args:
            ir: FeatureGraphIR to validate
            constraints: Manufacturing constraints

        Returns:
            List of issues found (empty if valid)
        """
        raise NotImplementedError


# -----------------------------------------------------------------------------
# Sanity Rules (Basic Validity)
# -----------------------------------------------------------------------------

class PositiveDepthRule(ValidationRule):
    """Extrusion depth must be positive."""

    code = "SANITY_POSITIVE_DEPTH"
    category = ValidationCategory.SANITY

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []

        for feature in ir.features:
            if feature.type.value in ("extrude", "cut"):
                depth = feature.params.get("depth", 0)
                if depth <= 0:
                    issues.append(ValidationIssue(
                        code=self.code,
                        message=f"Extrusion depth must be positive, got {depth}",
                        severity=ValidationSeverity.ERROR,
                        category=self.category,
                        feature_id=feature.id,
                        param_name="depth",
                        actual_value=depth,
                        allowed_range=(constraints.min_extrusion_depth, None)
                    ))

        return issues


class PositiveRadiusRule(ValidationRule):
    """Circle/fillet radius must be positive."""

    code = "SANITY_POSITIVE_RADIUS"
    category = ValidationCategory.SANITY

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []

        # Check sketch primitives
        for sketch in ir.sketches:
            for prim in sketch.primitives:
                if prim.type.value == "circle":
                    radius = prim.params.get("radius", 0)
                    if radius <= 0:
                        issues.append(ValidationIssue(
                            code=self.code,
                            message=f"Circle radius must be positive, got {radius}",
                            severity=ValidationSeverity.ERROR,
                            category=self.category,
                            feature_id=sketch.id,
                            param_name="radius",
                            actual_value=radius
                        ))

        # Check fillet features
        for feature in ir.features:
            if feature.type.value == "fillet":
                radius = feature.params.get("radius", 0)
                if radius <= 0:
                    issues.append(ValidationIssue(
                        code=self.code,
                        message=f"Fillet radius must be positive, got {radius}",
                        severity=ValidationSeverity.ERROR,
                        category=self.category,
                        feature_id=feature.id,
                        param_name="radius",
                        actual_value=radius
                    ))

        return issues


class PositiveDimensionRule(ValidationRule):
    """Rectangle dimensions must be positive."""

    code = "SANITY_POSITIVE_DIMENSION"
    category = ValidationCategory.SANITY

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []

        for sketch in ir.sketches:
            for prim in sketch.primitives:
                if prim.type.value == "rectangle":
                    width = prim.params.get("width", 0)
                    height = prim.params.get("height", 0)

                    if width <= 0:
                        issues.append(ValidationIssue(
                            code=self.code,
                            message=f"Rectangle width must be positive, got {width}",
                            severity=ValidationSeverity.ERROR,
                            category=self.category,
                            feature_id=sketch.id,
                            param_name="width",
                            actual_value=width
                        ))

                    if height <= 0:
                        issues.append(ValidationIssue(
                            code=self.code,
                            message=f"Rectangle height must be positive, got {height}",
                            severity=ValidationSeverity.ERROR,
                            category=self.category,
                            feature_id=sketch.id,
                            param_name="height",
                            actual_value=height
                        ))

        return issues


class MaxDimensionRule(ValidationRule):
    """Dimensions must not exceed maximum."""

    code = "SANITY_MAX_DIMENSION"
    category = ValidationCategory.SANITY

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []
        max_dim = constraints.max_dimension

        # Check all parameters
        for param_name, param in ir.parameters.items():
            if param.value > max_dim:
                issues.append(ValidationIssue(
                    code=self.code,
                    message=f"Parameter {param_name} exceeds maximum ({param.value} > {max_dim})",
                    severity=ValidationSeverity.ERROR,
                    category=self.category,
                    param_name=param_name,
                    actual_value=param.value,
                    allowed_range=(0, max_dim)
                ))

        return issues


# -----------------------------------------------------------------------------
# Physics Rules (Geometric Feasibility)
# -----------------------------------------------------------------------------

class FilletRadiusRule(ValidationRule):
    """Fillet radius must be feasible for geometry."""

    code = "PHYSICS_FILLET_RADIUS"
    category = ValidationCategory.PHYSICS

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []

        for feature in ir.features:
            if feature.type.value == "fillet":
                radius = feature.params.get("radius", 0)

                # Without full geometry, we can only check minimum
                if radius < constraints.min_fillet_radius:
                    issues.append(ValidationIssue(
                        code=self.code,
                        message=f"Fillet radius {radius}mm is below minimum {constraints.min_fillet_radius}mm",
                        severity=ValidationSeverity.WARNING,
                        category=self.category,
                        feature_id=feature.id,
                        param_name="radius",
                        actual_value=radius,
                        allowed_range=(constraints.min_fillet_radius, None)
                    ))

        return issues


class ChamferDistanceRule(ValidationRule):
    """Chamfer distance must be feasible."""

    code = "PHYSICS_CHAMFER_DISTANCE"
    category = ValidationCategory.PHYSICS

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []

        for feature in ir.features:
            if feature.type.value == "chamfer":
                distance = feature.params.get("distance", 0)

                if distance < constraints.min_chamfer_distance:
                    issues.append(ValidationIssue(
                        code=self.code,
                        message=f"Chamfer distance {distance}mm is below minimum {constraints.min_chamfer_distance}mm",
                        severity=ValidationSeverity.WARNING,
                        category=self.category,
                        feature_id=feature.id,
                        param_name="distance",
                        actual_value=distance,
                        allowed_range=(constraints.min_chamfer_distance, None)
                    ))

        return issues


# -----------------------------------------------------------------------------
# Manufacturing Rules (Producibility)
# -----------------------------------------------------------------------------

class MinWallThicknessRule(ValidationRule):
    """
    Wall thickness must meet minimum.

    Note: This is a heuristic check based on extrusion depth.
    Full wall thickness analysis requires compiled geometry.
    """

    code = "MFG_MIN_WALL_THICKNESS"
    category = ValidationCategory.MANUFACTURING

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []

        for feature in ir.features:
            if feature.type.value == "extrude":
                depth = feature.params.get("depth", 0)

                # Heuristic: if extrusion is very thin, warn
                if 0 < depth < constraints.min_wall_thickness:
                    issues.append(ValidationIssue(
                        code=self.code,
                        message=f"Extrusion depth {depth}mm may be below minimum wall thickness {constraints.min_wall_thickness}mm",
                        severity=ValidationSeverity.WARNING,
                        category=self.category,
                        feature_id=feature.id,
                        param_name="depth",
                        actual_value=depth,
                        allowed_range=(constraints.min_wall_thickness, None)
                    ))

        return issues


class MinHoleDiameterRule(ValidationRule):
    """Hole diameter must meet minimum for manufacturing."""

    code = "MFG_MIN_HOLE_DIAMETER"
    category = ValidationCategory.MANUFACTURING

    def validate(self, ir, constraints) -> List[ValidationIssue]:
        issues = []

        for sketch in ir.sketches:
            for prim in sketch.primitives:
                if prim.type.value == "circle":
                    diameter = prim.params.get("radius", 0) * 2

                    # Heuristic: small circles might be holes
                    if 0 < diameter < constraints.min_hole_diameter:
                        issues.append(ValidationIssue(
                            code=self.code,
                            message=f"Circle diameter {diameter}mm may be below minimum hole size {constraints.min_hole_diameter}mm",
                            severity=ValidationSeverity.WARNING,
                            category=self.category,
                            feature_id=sketch.id,
                            param_name="diameter",
                            actual_value=diameter,
                            allowed_range=(constraints.min_hole_diameter, None)
                        ))

        return issues


# =============================================================================
# Pre-Compilation Validator
# =============================================================================

class PreCompilationValidator:
    """
    Validates FeatureGraphIR before compilation.

    Usage:
        validator = PreCompilationValidator()
        result = validator.validate(ir)

        if not result.is_valid:
            raise ValidationError(result.issues)
    """

    DEFAULT_RULES = [
        # Sanity rules
        PositiveDepthRule(),
        PositiveRadiusRule(),
        PositiveDimensionRule(),
        MaxDimensionRule(),
        # Physics rules
        FilletRadiusRule(),
        ChamferDistanceRule(),
        # Manufacturing rules
        MinWallThicknessRule(),
        MinHoleDiameterRule(),
    ]

    def __init__(
        self,
        constraints: Optional[ManufacturingConstraints] = None,
        rules: Optional[List[ValidationRule]] = None
    ):
        """
        Initialize validator.

        Args:
            constraints: Manufacturing constraints (default for general use)
            rules: Custom validation rules (default rules if None)
        """
        self.constraints = constraints or ManufacturingConstraints()
        self.rules = rules or self.DEFAULT_RULES

    def validate(self, ir: Any) -> ValidationResult:
        """
        Run all validation rules.

        Args:
            ir: FeatureGraphIR to validate

        Returns:
            ValidationResult with all issues found
        """
        result = ValidationResult(is_valid=True)

        for rule in self.rules:
            try:
                issues = rule.validate(ir, self.constraints)
                for issue in issues:
                    result.add_issue(issue)
            except Exception as e:
                logger.error(f"Validation rule {rule.code} failed: {e}")
                result.add_issue(ValidationIssue(
                    code="VALIDATION_ERROR",
                    message=f"Rule {rule.code} failed: {e}",
                    severity=ValidationSeverity.ERROR,
                    category=ValidationCategory.SANITY
                ))

        logger.info(
            f"Validation complete: {result.errors} errors, "
            f"{result.warnings} warnings"
        )

        return result

    def validate_or_raise(self, ir: Any) -> None:
        """
        Validate and raise exception if invalid.

        Args:
            ir: FeatureGraphIR to validate

        Raises:
            ValueError: If validation fails with errors
        """
        result = self.validate(ir)

        if not result.is_valid:
            error_messages = [
                f"[{i.code}] {i.message}"
                for i in result.issues
                if i.severity == ValidationSeverity.ERROR
            ]
            raise ValueError(
                f"Pre-compilation validation failed with {result.errors} errors:\n"
                + "\n".join(error_messages)
            )


# =============================================================================
# Convenience Functions
# =============================================================================

def validate_for_3d_printing(ir: Any) -> ValidationResult:
    """Validate IR for 3D printing."""
    validator = PreCompilationValidator(
        constraints=ManufacturingConstraints.for_3d_printing()
    )
    return validator.validate(ir)


def validate_for_cnc(ir: Any) -> ValidationResult:
    """Validate IR for CNC milling."""
    validator = PreCompilationValidator(
        constraints=ManufacturingConstraints.for_cnc_milling()
    )
    return validator.validate(ir)


def validate_for_injection_molding(ir: Any) -> ValidationResult:
    """Validate IR for injection molding."""
    validator = PreCompilationValidator(
        constraints=ManufacturingConstraints.for_injection_molding()
    )
    return validator.validate(ir)
