"""
Tests for ConstructionPlan domain model.
"""
import pytest
from app.domain.construction_plan import ConstructionPlan, PlanParameter, ConstructionStep


class TestPlanParameter:
    """Tests for PlanParameter model."""
    
    def test_basic_parameter(self):
        """Test basic parameter creation."""
        param = PlanParameter(unit="mm", default=50.0)
        assert param.unit == "mm"
        assert param.default == 50.0
        assert param.depends_on is None
    
    def test_parameter_with_dependency(self):
        """Test parameter with dependency."""
        param = PlanParameter(unit="mm", default=5.0, depends_on="height")
        assert param.depends_on == "height"
    
    def test_parameter_with_range(self):
        """Test parameter with min/max range."""
        param = PlanParameter(unit="mm", default=50.0, min_value=10.0, max_value=100.0)
        assert param.min_value == 10.0
        assert param.max_value == 100.0
    
    def test_negative_default_rejected(self):
        """Test that negative defaults are rejected."""
        with pytest.raises(ValueError, match="non-negative"):
            PlanParameter(unit="mm", default=-10.0)


class TestConstructionPlan:
    """Tests for ConstructionPlan model."""
    
    def test_minimal_valid_plan(self):
        """Test minimal valid construction plan."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[
                ConstructionStep(order=1, description="Create base sketch"),
                ConstructionStep(order=2, description="Extrude")
            ]
        )
        assert plan.base_reference == "XY plane"
        assert len(plan.construction_sequence) == 2
        assert plan.is_valid()
    
    def test_full_plan(self):
        """Test construction plan with all fields."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[
                ConstructionStep(order=1, description="Create base sketch: rectangle", feature_type="sketch"),
                ConstructionStep(order=2, description="Extrude symmetrically", feature_type="extrude"),
                ConstructionStep(order=3, description="Apply fillet only on top edges", feature_type="fillet")
            ],
            parameters={
                "length": PlanParameter(unit="mm", default=50),
                "width": PlanParameter(unit="mm", default=30),
                "height": PlanParameter(unit="mm", default=20),
                "fillet_radius": PlanParameter(unit="mm", default=5, depends_on="height")
            },
            assumptions=["Sharp edges allowed on bottom"],
            open_questions=[],
            manufacturing_constraints=["Minimum wall thickness 2mm"],
            design_rationale="Standard bracket design"
        )
        
        assert plan.is_valid()
        assert not plan.has_open_questions()
        assert len(plan.parameters) == 4
        assert len(plan.assumptions) == 1
    
    def test_plan_with_open_questions(self):
        """Test plan with open questions."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[ConstructionStep(order=1, description="Create base sketch")],
            open_questions=["What is the preferred fillet radius?"]
        )
        assert plan.has_open_questions()
    
    def test_circular_dependency_validation(self):
        """Test that circular dependencies are caught."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="circular dependency"):
            ConstructionPlan(
                base_reference="XY plane",
                construction_sequence=[ConstructionStep(order=1, description="Create sketch")],
                parameters={
                    "width": PlanParameter(default=50, depends_on="width")  # Self-reference
                }
            )
    
    def test_unknown_dependency_validation(self):
        """Test that unknown dependencies are caught."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="depends on unknown"):
            ConstructionPlan(
                base_reference="XY plane",
                construction_sequence=[ConstructionStep(order=1, description="Create sketch")],
                parameters={
                    "width": PlanParameter(default=50, depends_on="nonexistent")
                }
            )
    
    def test_invalid_range_validation(self):
        """Test that invalid min/max ranges are caught."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[ConstructionStep(order=1, description="Create sketch")],
            parameters={
                "width": PlanParameter(default=50, min_value=100, max_value=10)  # min > max
            }
        )
        errors = plan.validate_plan()
        assert any("invalid range" in e for e in errors)
    
    def test_default_below_min_validation(self):
        """Test that default below min is caught."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[ConstructionStep(order=1, description="Create sketch")],
            parameters={
                "width": PlanParameter(default=5, min_value=10, max_value=100)
            }
        )
        errors = plan.validate_plan()
        assert any("below minimum" in e for e in errors)
    
    def test_to_prompt_context(self):
        """Test conversion to prompt context string."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[
                ConstructionStep(order=1, description="Create rectangle"),
                ConstructionStep(order=2, description="Extrude")
            ],
            parameters={
                "width": PlanParameter(unit="mm", default=50)
            },
            assumptions=["Centered on origin"]
        )
        context = plan.to_prompt_context()
        
        assert "XY plane" in context
        assert "Create rectangle" in context
        assert "50mm" in context or "50.0mm" in context
        assert "Centered on origin" in context
    
    def test_get_resolved_parameters(self):
        """Test parameter resolution."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[ConstructionStep(order=1, description="Create sketch")],
            parameters={
                "width": PlanParameter(default=50),
                "height": PlanParameter(default=30),
                "fillet": PlanParameter(default=5, depends_on="width")
            }
        )
        resolved = plan.get_resolved_parameters()
        
        assert resolved["width"] == 50
        assert resolved["height"] == 30
        assert resolved["fillet"] == 5


class TestConstructionPlanIntegration:
    """Integration tests for ConstructionPlan in the pipeline."""
    
    def test_plan_to_feature_graph_compatibility(self):
        """Test that plan parameters align with FeatureGraph expectations."""
        plan = ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[
                ConstructionStep(order=1, description="Create base sketch: rectangle with width and height parameters", feature_type="sketch"),
                ConstructionStep(order=2, description="Extrude to depth", feature_type="extrude")
            ],
            parameters={
                "width": PlanParameter(unit="mm", default=50),
                "height": PlanParameter(unit="mm", default=30),
                "depth": PlanParameter(unit="mm", default=10)
            }
        )
        
        # These are the parameters that would be passed to FeatureGraph
        resolved = plan.get_resolved_parameters()
        
        assert "width" in resolved
        assert "height" in resolved
        assert "depth" in resolved
        assert all(isinstance(v, (int, float)) for v in resolved.values())

