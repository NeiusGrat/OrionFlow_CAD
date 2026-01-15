"""
Test Phase 4: Two-Stage LLM Pipeline

Tests for:
- DesignIntent extraction
- Template selection
- Template parameter validation
- Two-stage generation flow
"""
import pytest
from app.domain.design_intent import DesignIntent, PartType, ManufacturingProcess
from app.templates.parametric_templates import (
    TemplateRegistry, BoxTemplate, BracketTemplate
)


def test_design_intent_creation():
    """Test DesignIntent model validation."""
    intent = DesignIntent(
        part_type=PartType.BOX,
        manufacturing_process=ManufacturingProcess.CNC_MILLING,
        symmetry=False,
        key_dimensions={"width": 100, "depth": 50, "height": 30}
    )
    
    assert intent.part_type == "box"
    assert intent.template_name() == "BoxTemplate"
    assert intent.validate_for_template() == []  # No missing dims
    
    print("✓ DesignIntent creation works")


def test_template_selection():
    """Test automatic template selection from intent."""
    intent = DesignIntent(
        part_type=PartType.BRACKET,
        key_dimensions={"base_width": 60, "vertical_height": 70, "thickness": 8}
    )
    
    template = TemplateRegistry.select_template(intent)
    assert template is not None
    assert template.name == "BracketTemplate"
    
    print("✓ Template selection works")


def test_box_template_generation():
    """Test BoxTemplate generates valid FeatureGraph."""
    intent = DesignIntent(
        part_type=PartType.BOX,
        key_dimensions={"width": 100, "depth": 50, "height": 30}
    )
    
    template = BoxTemplate()
    feature_graph = template.generate(intent)
    
    assert feature_graph.version == "3.0"
    assert "width" in feature_graph.parameters
    assert len(feature_graph.sketches) > 0
    assert len(feature_graph.features) > 0
    
    # Check safe fillet radius
    fillet_feature = [f for f in feature_graph.features if f.type == "fillet"][0]
    assert "$fillet_radius" in str(fillet_feature.params.get("radius"))
    
    print("✓ BoxTemplate generation works")


def test_missing_dimensions_detection():
    """Test that missing dimensions are caught."""
    intent = DesignIntent(
        part_type=PartType.BOX,
        key_dimensions={"width": 100}  # Missing depth, height!
    )
    
    missing = intent.validate_for_template()
    assert "depth" in missing
    assert "height" in missing
    
    print("✓ Missing dimensions detected")


def test_template_registry():
    """Test template registry lists all templates."""
    templates = TemplateRegistry.list_templates()
    
    assert "BoxTemplate" in templates
    assert "BracketTemplate" in templates
    assert "PlateWithHolesTemplate" in templates
    assert "ShaftTemplate" in templates
    
    print("✓ Template registry complete")


def test_manufacturing_constraints_in_template():
    """Test that templates apply manufacturing constraints."""
    intent = DesignIntent(
        part_type=PartType.BRACKET,
        manufacturing_process=ManufacturingProcess.CNC_MILLING,
        key_dimensions={"base_width": 50, "vertical_height": 60, "thickness": 6}
    )
    
    template = BracketTemplate()
    feature_graph = template.generate(intent)
    
    # Check that fillet radius respects CNC constraints (min 1.5mm)
    fillet_param = feature_graph.parameters.get("fillet_radius")
    assert fillet_param >= 1.5, "Fillet radius should respect CNC min tool size"
    
    print("✓ Manufacturing constraints applied")


if __name__ == "__main__":
    test_design_intent_creation()
    test_template_selection()
    test_box_template_generation()
    test_missing_dimensions_detection()
    test_template_registry()
    test_manufacturing_constraints_in_template()
    print("\n✅ All Phase 4 tests passed!")
