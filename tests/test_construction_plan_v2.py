"""
Tests for ConstructionPlan v2 - The Intelligence Boundary.

These tests ensure the ConstructionPlan is a proper first-class domain object:
1. Persistence and reconstruction
2. Lifecycle management (draft -> approved -> executed)
3. Editing support
4. Validation
"""
import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import json

from app.domain.construction_plan import (
    ConstructionPlan,
    ConstructionStep,
    PlanParameter,
    PlanStatus,
    PlanSource,
    PlanPersistence
)


class TestPlanParameter:
    """Tests for PlanParameter validation."""

    def test_valid_parameter(self):
        """Valid parameter with all fields."""
        param = PlanParameter(
            unit="mm",
            default=50.0,
            min_value=1.0,
            max_value=100.0,
            semantic_name="Test Width",
            reasoning="Test reasoning"
        )
        assert param.default == 50.0
        assert param.semantic_name == "Test Width"

    def test_negative_parameter_fails(self):
        """Negative default should fail."""
        with pytest.raises(ValueError, match="non-negative"):
            PlanParameter(unit="mm", default=-10.0)

    def test_validate_value_below_minimum(self):
        """Value below minimum should report error."""
        param = PlanParameter(unit="mm", default=10.0, min_value=5.0)
        errors = param.validate_value(3.0)
        assert len(errors) == 1
        assert "below minimum" in errors[0]

    def test_validate_value_above_maximum(self):
        """Value above maximum should report error."""
        param = PlanParameter(unit="mm", default=10.0, max_value=20.0)
        errors = param.validate_value(25.0)
        assert len(errors) == 1
        assert "above maximum" in errors[0]


class TestConstructionStep:
    """Tests for ConstructionStep."""

    def test_valid_step(self):
        """Valid construction step."""
        step = ConstructionStep(
            order=1,
            description="Create base sketch",
            feature_type="sketch",
            sketch_required=True,
            parameters_used=["width", "height"],
            reasoning="Starting point for 3D geometry"
        )
        assert step.order == 1
        assert step.feature_type == "sketch"
        assert "width" in step.parameters_used


class TestConstructionPlan:
    """Tests for ConstructionPlan lifecycle and validation."""

    @pytest.fixture
    def sample_plan(self):
        """Create a sample plan for testing."""
        return ConstructionPlan(
            prompt="Create a 50mm cube",
            source=PlanSource.HEURISTIC,
            status=PlanStatus.DRAFT,
            construction_sequence=[
                ConstructionStep(
                    order=1,
                    description="Create base sketch on XY plane",
                    feature_type="sketch",
                    sketch_required=True,
                    parameters_used=["width", "height"]
                ),
                ConstructionStep(
                    order=2,
                    description="Extrude to depth",
                    feature_type="extrude",
                    sketch_required=False,
                    parameters_used=["depth"]
                )
            ],
            parameters={
                "width": PlanParameter(unit="mm", default=50.0),
                "height": PlanParameter(unit="mm", default=50.0),
                "depth": PlanParameter(unit="mm", default=50.0)
            },
            assumptions=["Centered on origin"],
            design_rationale="Simple cube per user request"
        )

    def test_plan_has_unique_id(self, sample_plan):
        """Plan should have unique ID."""
        assert sample_plan.id.startswith("plan_")
        assert len(sample_plan.id) > 10

    def test_plan_has_timestamp(self, sample_plan):
        """Plan should have creation timestamp."""
        assert sample_plan.created_at is not None
        assert isinstance(sample_plan.created_at, datetime)

    def test_plan_validation_passes(self, sample_plan):
        """Valid plan should pass validation."""
        errors = sample_plan.validate_plan()
        assert len(errors) == 0
        assert sample_plan.is_valid()

    def test_empty_construction_sequence_fails(self):
        """Plan with empty construction sequence should fail validation."""
        plan = ConstructionPlan(
            prompt="test",
            construction_sequence=[],
            parameters={}
        )
        errors = plan.validate_plan()
        assert any("empty" in e.lower() for e in errors)

    def test_unknown_parameter_reference_fails(self):
        """Step referencing unknown parameter should fail."""
        plan = ConstructionPlan(
            prompt="test",
            construction_sequence=[
                ConstructionStep(
                    order=1,
                    description="Test",
                    parameters_used=["nonexistent"]
                )
            ],
            parameters={}
        )
        errors = plan.validate_plan()
        assert any("unknown parameter" in e.lower() for e in errors)

    def test_circular_dependency_fails(self):
        """Circular parameter dependency should fail."""
        with pytest.raises(ValueError, match="circular"):
            ConstructionPlan(
                prompt="test",
                construction_sequence=[
                    ConstructionStep(order=1, description="Test")
                ],
                parameters={
                    "width": PlanParameter(
                        unit="mm",
                        default=10.0,
                        depends_on="width"  # Self-dependency
                    )
                }
            )


class TestPlanLifecycle:
    """Tests for plan lifecycle management."""

    @pytest.fixture
    def draft_plan(self):
        """Create a draft plan."""
        return ConstructionPlan(
            prompt="test",
            status=PlanStatus.DRAFT,
            construction_sequence=[
                ConstructionStep(order=1, description="Test step")
            ]
        )

    def test_approve_plan(self, draft_plan):
        """Approving a plan should change status."""
        approved = draft_plan.approve()
        assert approved.status == PlanStatus.APPROVED
        assert approved.updated_at is not None
        # Original should be unchanged
        assert draft_plan.status == PlanStatus.DRAFT

    def test_approve_plan_with_open_questions_fails(self):
        """Cannot approve plan with open questions."""
        plan = ConstructionPlan(
            prompt="test",
            construction_sequence=[
                ConstructionStep(order=1, description="Test")
            ],
            open_questions=["What size?"]
        )
        with pytest.raises(ValueError, match="open questions"):
            plan.approve()

    def test_reject_plan(self, draft_plan):
        """Rejecting a plan should record reason."""
        rejected = draft_plan.reject("Design is too complex")
        assert rejected.status == PlanStatus.REJECTED
        assert rejected.execution_error == "Design is too complex"

    def test_mark_executed(self, draft_plan):
        """Marking as executed should link to FeatureGraph."""
        approved = draft_plan.approve()
        executed = approved.mark_executed("fg_abc123")
        assert executed.status == PlanStatus.EXECUTED
        assert executed.feature_graph_id == "fg_abc123"

    def test_is_ready_for_execution(self, draft_plan):
        """Draft plan should not be ready for execution."""
        assert not draft_plan.is_ready_for_execution()

        approved = draft_plan.approve()
        assert approved.is_ready_for_execution()


class TestPlanEditing:
    """Tests for plan editing support."""

    @pytest.fixture
    def editable_plan(self):
        """Create a plan for editing tests."""
        return ConstructionPlan(
            prompt="test",
            construction_sequence=[
                ConstructionStep(order=1, description="Initial step")
            ],
            parameters={
                "width": PlanParameter(
                    unit="mm",
                    default=50.0,
                    min_value=10.0,
                    max_value=100.0
                )
            }
        )

    def test_update_parameter(self, editable_plan):
        """Updating parameter should create new version."""
        updated = editable_plan.update_parameter("width", 75.0, "User requested larger")
        assert updated.parameters["width"].default == 75.0
        assert updated.version == 2
        assert updated.updated_at is not None
        # Original unchanged
        assert editable_plan.parameters["width"].default == 50.0

    def test_update_parameter_out_of_range_fails(self, editable_plan):
        """Updating with out-of-range value should fail."""
        with pytest.raises(ValueError, match="Invalid value"):
            editable_plan.update_parameter("width", 5.0)  # Below minimum

    def test_update_unknown_parameter_fails(self, editable_plan):
        """Updating unknown parameter should fail."""
        with pytest.raises(ValueError, match="Unknown parameter"):
            editable_plan.update_parameter("nonexistent", 10.0)

    def test_add_step(self, editable_plan):
        """Adding step should increment order."""
        updated = editable_plan.add_step(
            description="Added step",
            feature_type="fillet"
        )
        assert len(updated.construction_sequence) == 2
        assert updated.construction_sequence[-1].order == 2
        assert updated.version == 2

    def test_resolve_question(self):
        """Resolving question should add to assumptions."""
        plan = ConstructionPlan(
            prompt="test",
            construction_sequence=[
                ConstructionStep(order=1, description="Test")
            ],
            open_questions=["What is the material?"]
        )
        resolved = plan.resolve_question(
            "What is the material?",
            "Aluminum 6061"
        )
        assert len(resolved.open_questions) == 0
        assert any("Aluminum" in a for a in resolved.assumptions)


class TestPlanPersistence:
    """Tests for plan persistence."""

    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def persistence(self, temp_storage):
        """Create persistence service."""
        return PlanPersistence(storage_dir=temp_storage)

    @pytest.fixture
    def sample_plan(self):
        """Create a sample plan."""
        return ConstructionPlan(
            prompt="Test persistence",
            construction_sequence=[
                ConstructionStep(
                    order=1,
                    description="Test step",
                    feature_type="extrude"
                )
            ],
            parameters={
                "height": PlanParameter(unit="mm", default=20.0)
            }
        )

    def test_save_and_load(self, persistence, sample_plan):
        """Plan should survive save/load cycle."""
        # Save
        path = persistence.save(sample_plan)
        assert Path(path).exists()

        # Load
        loaded = persistence.load(sample_plan.id)
        assert loaded is not None
        assert loaded.id == sample_plan.id
        assert loaded.prompt == sample_plan.prompt
        assert loaded.parameters["height"].default == 20.0
        assert len(loaded.construction_sequence) == 1

    def test_load_nonexistent_returns_none(self, persistence):
        """Loading nonexistent plan should return None."""
        loaded = persistence.load("nonexistent_plan")
        assert loaded is None

    def test_list_plans(self, persistence, sample_plan):
        """Should list all saved plans."""
        persistence.save(sample_plan)
        plan_ids = persistence.list_plans()
        assert sample_plan.id in plan_ids

    def test_list_plans_by_status(self, persistence, sample_plan):
        """Should filter plans by status."""
        # Create a second plan that is approved
        approved_plan = ConstructionPlan(
            prompt="Approved plan",
            status=PlanStatus.APPROVED,
            construction_sequence=[
                ConstructionStep(order=1, description="Step 1")
            ]
        )
        
        persistence.save(sample_plan)   # Draft
        persistence.save(approved_plan) # Approved

        draft_plans = persistence.list_plans(status=PlanStatus.DRAFT)
        approved_plans = persistence.list_plans(status=PlanStatus.APPROVED)

        assert sample_plan.id in draft_plans
        assert approved_plan.id in approved_plans


class TestPromptContext:
    """Tests for LLM prompt context generation."""

    def test_to_prompt_context(self):
        """Should generate readable context."""
        plan = ConstructionPlan(
            prompt="Test",
            construction_sequence=[
                ConstructionStep(
                    order=1,
                    description="Create sketch",
                    feature_type="sketch"
                ),
                ConstructionStep(
                    order=2,
                    description="Extrude",
                    feature_type="extrude"
                )
            ],
            parameters={
                "width": PlanParameter(unit="mm", default=50.0)
            },
            assumptions=["Centered"]
        )
        context = plan.to_prompt_context()

        assert "Plan ID:" in context
        assert "Create sketch" in context
        assert "[sketch]" in context
        assert "width: 50.0mm" in context
        assert "Centered" in context


class TestHashAndDeduplication:
    """Tests for content hashing."""

    def test_same_content_same_hash(self):
        """Plans with same content should have same hash."""
        plan1 = ConstructionPlan(
            prompt="Test 1",  # Different prompt
            construction_sequence=[
                ConstructionStep(order=1, description="Step 1")
            ],
            parameters={"width": PlanParameter(unit="mm", default=50.0)}
        )
        plan2 = ConstructionPlan(
            prompt="Test 2",  # Different prompt
            construction_sequence=[
                ConstructionStep(order=1, description="Step 1")
            ],
            parameters={"width": PlanParameter(unit="mm", default=50.0)}
        )
        # Hash based on content, not metadata
        assert plan1.compute_hash() == plan2.compute_hash()

    def test_different_content_different_hash(self):
        """Plans with different content should have different hash."""
        plan1 = ConstructionPlan(
            prompt="Test",
            construction_sequence=[
                ConstructionStep(order=1, description="Step 1")
            ],
            parameters={"width": PlanParameter(unit="mm", default=50.0)}
        )
        plan2 = ConstructionPlan(
            prompt="Test",
            construction_sequence=[
                ConstructionStep(order=1, description="Step 2")  # Different
            ],
            parameters={"width": PlanParameter(unit="mm", default=50.0)}
        )
        assert plan1.compute_hash() != plan2.compute_hash()
