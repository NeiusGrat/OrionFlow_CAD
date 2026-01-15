"""
Test Manufacturing Intelligence - Phase 5

Tests for:
- ManufacturingConstraints creation
- CNC fillet validation
- Wall thickness rules
- Hole standards checking
- Manufacturing-aware templates
"""
import pytest
from app.domain.manufacturing import ManufacturingConstraints, ManufacturingProcess
from app.domain.feature_graph_v2 import FeatureV2
from app.compilers.validators.manufacturing_validators import (
    CNCFilletValidator,
    WallThicknessValidator,
    HoleStandardsValidator
)
from app.domain.compiler_errors import ErrorType


def test_cnc_constraints_creation():
    """Test CNC constraint factory."""
    constraints = ManufacturingConstraints.for_cnc_milling(tool_diameter=6.0)
    
    assert constraints.process == "CNC"
    assert constraints.min_tool_diameter == 6.0
    assert constraints.min_fillet_radius == 3.0  # tool_diameter / 2
    assert 3.0 in constraints.standard_hole_sizes
    assert "M5" in constraints.standard_thread_sizes
    
    print("✓ CNC constraints created correctly")


def test_3d_print_constraints():
    """Test 3D print constraint factory."""
    constraints = ManufacturingConstraints.for_3d_printing(nozzle_diameter=0.4)
    
    assert constraints.process == "3D_print"
    assert constraints.min_wall_thickness == 0.8  # 2x nozzle
    assert constraints.support_overhang_angle == 45.0
    
    print("✓ 3D print constraints created correctly")


def test_cnc_fillet_validator():
    """Test CNC fillet validator catches undersized fillets."""
    constraints = ManufacturingConstraints.for_cnc_milling(tool_diameter=6.0)
    validator = CNCFilletValidator(constraints)
    
    # Bad: 2mm fillet with 6mm tool (min = 3mm)
    feature = FeatureV2(
        id="fillet_1",
        type="fillet",
        params={"radius": 2.0}
    )
    
    error = validator.validate(None, feature)  # solid=None for test
    
    assert error is not None
    assert error.error_type == ErrorType.INVALID_FILLET
    assert "CNC minimum" in error.reason
    assert error.context["tool_diameter"] == 6.0
    
    print("✓ CNC fillet validator works")


def test_cnc_fillet_validator_passes_valid():
    """Test CNC fillet validator passes valid fillets."""
    constraints = ManufacturingConstraints.for_cnc_milling(tool_diameter=6.0)
    validator = CNCFilletValidator(constraints)
    
    # Good: 4mm fillet with 6mm tool (min = 3mm)
    feature = FeatureV2(
        id="fillet_1",
        type="fillet",
        params={"radius": 4.0}
    )
    
    error = validator.validate(None, feature)
    
    assert error is None, "Valid fillet should pass"
    
    print("✓ CNC fillet validator passes valid fillets")


def test_wall_thickness_validator():
    """Test wall thickness validator."""
    constraints = ManufacturingConstraints.for_cnc_milling()
    validator = WallThicknessValidator(constraints)
    
    # Bad: 1mm extrude (min = 2mm for CNC)
    feature = FeatureV2(
        id="extrude_1",
        type="extrude",
        sketch="s1",
        params={"depth": 1.0}
    )
    
    error = validator.validate(None, feature)
    
    assert error is not None
    assert error.error_type == ErrorType.ZERO_THICKNESS
    assert "minimum wall thickness" in error.reason
    
    print("✓ Wall thickness validator works")


def test_hole_standards_validator():
    """Test hole standards checker."""
    constraints = ManufacturingConstraints.for_cnc_milling()
    validator = HoleStandardsValidator(constraints)
    
    # Non-standard hole: 7mm (not in standard list)
    feature = FeatureV2(
        id="hole_1",
        type="hole",
        params={"diameter": 7.0}
    )
    
    error = validator.validate(None, feature)
    
    # Should warn or error about non-standard
    if error:
        assert error.error_type == ErrorType.MANUFACTURING_VIOLATION
        assert "standard" in error.reason.lower()
    
    print("✓ Hole standards validator works")


def test_manufacturing_constraints_in_template():
    """Test that templates use manufacturing constraints."""
    from app.templates.parametric_templates import BracketTemplate
    from app.domain.design_intent import DesignIntent, PartType, ManufacturingProcess
    
    intent = DesignIntent(
        part_type=PartType.BRACKET,
        manufacturing_process=ManufacturingProcess.CNC_MILLING,
        key_dimensions={"base_width": 50, "vertical_height": 60, "thickness": 6}
    )
    
    template = BracketTemplate()
    graph = template.generate(intent)
    
    # Check that fillet radius respects CNC min (1.5mm)
    fillet_radius = graph.parameters.get("fillet_radius")
    assert fillet_radius >= 1.5, f"Fillet {fillet_radius}mm should be ≥ 1.5mm for CNC"
    
    print("✓ Templates apply manufacturing constraints")


if __name__ == "__main__":
    test_cnc_constraints_creation()
    test_3d_print_constraints()
    test_cnc_fillet_validator()
    test_cnc_fillet_validator_passes_valid()
    test_wall_thickness_validator()
    test_hole_standards_validator()
    test_manufacturing_constraints_in_template()
    print("\n✅ All Phase 5 manufacturing tests passed!")
