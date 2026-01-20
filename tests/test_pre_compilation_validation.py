"""
Tests for Pre-Compilation Validation (STEP 4).

Tests symbolic and manufacturing constraints:
1. Sanity checks (positive dimensions)
2. Physics constraints (fillet feasibility)
3. Manufacturing constraints (wall thickness)
"""
import pytest
from unittest.mock import MagicMock
from app.validation.pre_compilation import (
    ValidationSeverity,
    ValidationCategory,
    ValidationIssue,
    ValidationResult,
    ManufacturingConstraints,
    PreCompilationValidator,
    PositiveDepthRule,
    PositiveRadiusRule,
    PositiveDimensionRule,
    FilletRadiusRule,
    MinWallThicknessRule,
    validate_for_3d_printing,
    validate_for_cnc
)


# =============================================================================
# Mock IR Objects for Testing
# =============================================================================

class MockPrimitive:
    """Mock sketch primitive."""
    def __init__(self, prim_type, params):
        self.type = MagicMock(value=prim_type)
        self.params = params


class MockSketch:
    """Mock sketch."""
    def __init__(self, sketch_id, primitives):
        self.id = sketch_id
        self.primitives = primitives


class MockFeature:
    """Mock feature."""
    def __init__(self, feature_id, feature_type, params):
        self.id = feature_id
        self.type = MagicMock(value=feature_type)
        self.params = params


class MockParameter:
    """Mock resolved parameter."""
    def __init__(self, value):
        self.value = value


class MockIR:
    """Mock FeatureGraphIR."""
    def __init__(self, sketches=None, features=None, parameters=None):
        self.sketches = sketches or []
        self.features = features or []
        self.parameters = parameters or {}


# =============================================================================
# Test ValidationResult
# =============================================================================

class TestValidationResult:
    """Tests for ValidationResult."""

    def test_initially_valid(self):
        """Result starts as valid."""
        result = ValidationResult(is_valid=True)
        assert result.is_valid
        assert result.errors == 0
        assert result.warnings == 0

    def test_add_error_invalidates(self):
        """Adding error makes result invalid."""
        result = ValidationResult(is_valid=True)
        result.add_issue(ValidationIssue(
            code="TEST",
            message="Test error",
            severity=ValidationSeverity.ERROR,
            category=ValidationCategory.SANITY
        ))
        assert not result.is_valid
        assert result.errors == 1

    def test_add_warning_keeps_valid(self):
        """Adding warning keeps result valid."""
        result = ValidationResult(is_valid=True)
        result.add_issue(ValidationIssue(
            code="TEST",
            message="Test warning",
            severity=ValidationSeverity.WARNING,
            category=ValidationCategory.MANUFACTURING
        ))
        assert result.is_valid
        assert result.warnings == 1

    def test_to_dict(self):
        """Result can be serialized."""
        result = ValidationResult(is_valid=True)
        result.add_issue(ValidationIssue(
            code="TEST",
            message="Test",
            severity=ValidationSeverity.ERROR,
            category=ValidationCategory.SANITY
        ))
        data = result.to_dict()
        assert "is_valid" in data
        assert "errors" in data
        assert "issues" in data


# =============================================================================
# Test Manufacturing Constraints
# =============================================================================

class TestManufacturingConstraints:
    """Tests for ManufacturingConstraints presets."""

    def test_default_constraints(self):
        """Default constraints have sensible values."""
        c = ManufacturingConstraints()
        assert c.min_wall_thickness > 0
        assert c.min_fillet_radius > 0

    def test_3d_printing_constraints(self):
        """3D printing constraints are appropriate."""
        c = ManufacturingConstraints.for_3d_printing()
        assert c.min_wall_thickness >= 0.8  # Typical FDM minimum
        assert c.min_hole_diameter >= 0.5

    def test_cnc_constraints(self):
        """CNC constraints account for tool size."""
        c = ManufacturingConstraints.for_cnc_milling()
        assert c.min_fillet_radius >= 1.5  # Min end mill radius
        assert c.min_hole_diameter >= 3.0

    def test_injection_molding_constraints(self):
        """Injection molding has draft angle."""
        c = ManufacturingConstraints.for_injection_molding()
        assert c.min_draft_angle >= 1.0


# =============================================================================
# Test Sanity Rules
# =============================================================================

class TestSanityRules:
    """Tests for basic sanity validation rules."""

    def test_positive_depth_valid(self):
        """Valid extrusion depth passes."""
        ir = MockIR(features=[
            MockFeature("f1", "extrude", {"depth": 10.0})
        ])
        rule = PositiveDepthRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 0

    def test_positive_depth_zero_fails(self):
        """Zero depth fails validation."""
        ir = MockIR(features=[
            MockFeature("f1", "extrude", {"depth": 0})
        ])
        rule = PositiveDepthRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR

    def test_positive_depth_negative_fails(self):
        """Negative depth fails validation."""
        ir = MockIR(features=[
            MockFeature("f1", "extrude", {"depth": -5.0})
        ])
        rule = PositiveDepthRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 1

    def test_positive_radius_valid(self):
        """Valid circle radius passes."""
        ir = MockIR(sketches=[
            MockSketch("s1", [
                MockPrimitive("circle", {"radius": 10.0})
            ])
        ])
        rule = PositiveRadiusRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 0

    def test_positive_radius_zero_fails(self):
        """Zero radius fails validation."""
        ir = MockIR(sketches=[
            MockSketch("s1", [
                MockPrimitive("circle", {"radius": 0})
            ])
        ])
        rule = PositiveRadiusRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 1

    def test_positive_fillet_radius_valid(self):
        """Valid fillet radius passes."""
        ir = MockIR(features=[
            MockFeature("f1", "fillet", {"radius": 2.0})
        ])
        rule = PositiveRadiusRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 0

    def test_positive_dimension_valid(self):
        """Valid rectangle dimensions pass."""
        ir = MockIR(sketches=[
            MockSketch("s1", [
                MockPrimitive("rectangle", {"width": 50.0, "height": 30.0})
            ])
        ])
        rule = PositiveDimensionRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 0

    def test_positive_dimension_zero_width_fails(self):
        """Zero width fails validation."""
        ir = MockIR(sketches=[
            MockSketch("s1", [
                MockPrimitive("rectangle", {"width": 0, "height": 30.0})
            ])
        ])
        rule = PositiveDimensionRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 1


# =============================================================================
# Test Physics Rules
# =============================================================================

class TestPhysicsRules:
    """Tests for physics constraint validation."""

    def test_fillet_radius_valid(self):
        """Fillet above minimum passes."""
        ir = MockIR(features=[
            MockFeature("f1", "fillet", {"radius": 2.0})
        ])
        rule = FilletRadiusRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        # Should pass (radius > min_fillet_radius of 0.1)
        assert all(i.severity != ValidationSeverity.ERROR for i in issues)

    def test_fillet_radius_too_small_warns(self):
        """Fillet below minimum warns."""
        constraints = ManufacturingConstraints(min_fillet_radius=1.0)
        ir = MockIR(features=[
            MockFeature("f1", "fillet", {"radius": 0.5})
        ])
        rule = FilletRadiusRule()
        issues = rule.validate(ir, constraints)
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.WARNING


# =============================================================================
# Test Manufacturing Rules
# =============================================================================

class TestManufacturingRules:
    """Tests for manufacturing constraint validation."""

    def test_wall_thickness_valid(self):
        """Extrusion above minimum passes."""
        ir = MockIR(features=[
            MockFeature("f1", "extrude", {"depth": 10.0})
        ])
        rule = MinWallThicknessRule()
        issues = rule.validate(ir, ManufacturingConstraints())
        assert len(issues) == 0

    def test_wall_thickness_too_thin_warns(self):
        """Extrusion below minimum warns."""
        constraints = ManufacturingConstraints(min_wall_thickness=2.0)
        ir = MockIR(features=[
            MockFeature("f1", "extrude", {"depth": 0.5})
        ])
        rule = MinWallThicknessRule()
        issues = rule.validate(ir, constraints)
        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.WARNING


# =============================================================================
# Test Full Validator
# =============================================================================

class TestPreCompilationValidator:
    """Tests for the full validator."""

    def test_valid_ir_passes(self):
        """Valid IR passes all checks."""
        ir = MockIR(
            sketches=[
                MockSketch("s1", [
                    MockPrimitive("rectangle", {"width": 50.0, "height": 30.0})
                ])
            ],
            features=[
                MockFeature("f1", "extrude", {"depth": 10.0})
            ],
            parameters={}
        )
        validator = PreCompilationValidator()
        result = validator.validate(ir)
        assert result.is_valid

    def test_invalid_ir_fails(self):
        """Invalid IR fails validation."""
        ir = MockIR(
            sketches=[],
            features=[
                MockFeature("f1", "extrude", {"depth": -5.0})  # Invalid
            ],
            parameters={}
        )
        validator = PreCompilationValidator()
        result = validator.validate(ir)
        assert not result.is_valid
        assert result.errors > 0

    def test_validate_or_raise(self):
        """Invalid IR raises exception."""
        ir = MockIR(
            sketches=[],
            features=[
                MockFeature("f1", "extrude", {"depth": 0})  # Invalid
            ],
            parameters={}
        )
        validator = PreCompilationValidator()
        with pytest.raises(ValueError, match="validation failed"):
            validator.validate_or_raise(ir)

    def test_multiple_issues(self):
        """Multiple issues are collected."""
        ir = MockIR(
            sketches=[
                MockSketch("s1", [
                    MockPrimitive("circle", {"radius": 0}),  # Invalid
                    MockPrimitive("rectangle", {"width": 0, "height": 0})  # Invalid x2
                ])
            ],
            features=[
                MockFeature("f1", "extrude", {"depth": 0})  # Invalid
            ],
            parameters={}
        )
        validator = PreCompilationValidator()
        result = validator.validate(ir)
        assert result.errors >= 4  # At least 4 errors


# =============================================================================
# Test Convenience Functions
# =============================================================================

class TestConvenienceFunctions:
    """Tests for preset validation functions."""

    def test_validate_for_3d_printing(self):
        """3D printing validation uses correct constraints."""
        ir = MockIR(
            sketches=[],
            features=[
                MockFeature("f1", "extrude", {"depth": 0.3})  # Very thin
            ],
            parameters={}
        )
        result = validate_for_3d_printing(ir)
        # Should warn about thin wall for 3D printing
        assert result.warnings > 0 or result.errors > 0

    def test_validate_for_cnc(self):
        """CNC validation uses correct constraints."""
        ir = MockIR(
            sketches=[],
            features=[
                MockFeature("f1", "fillet", {"radius": 0.5})  # Too small for CNC
            ],
            parameters={}
        )
        result = validate_for_cnc(ir)
        # Should warn about small fillet for CNC (min is 1.5mm)
        assert result.warnings > 0 or result.errors > 0
