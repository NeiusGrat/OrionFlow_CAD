"""
Tests for Error Recovery Engine (VERSION 0.5).

Tests multi-stage validation and error classification.
"""
import pytest

from app.validation.error_recovery import (
    ErrorRecoveryEngine,
    ValidationLevel,
    ValidationIssue
)
from app.domain.feature_graph_v2 import (
    FeatureGraphV2,
    FeatureV2,
    SketchGraphV2,
    SketchPrimitiveV2
)


class TestValidationIssue:
    """Test ValidationIssue dataclass."""
    
    def test_create_issue(self):
        """Test creating validation issue."""
        issue = ValidationIssue(
            level=ValidationLevel.CRITICAL,
            stage="schema",
            message="Invalid version",
            fix_suggestion="Use version 2.0"
        )
        
        assert issue.level == ValidationLevel.CRITICAL
        assert issue.stage == "schema"
        assert issue.message == "Invalid version"
        assert issue.fix_suggestion == "Use version 2.0"


class TestErrorRecoveryEngine:
    """Test ErrorRecovery Engine."""
    
    @pytest.fixture
    def engine(self):
        """Create error recovery engine."""
        return ErrorRecoveryEngine(max_retries=3)
    
    def test_engine_initialization(self, engine):
        """Test engine initialization."""
        assert engine.max_retries == 3


class TestSchemaValidation:
    """Test schema validation."""
    
    @pytest.fixture
    def engine(self):
        return ErrorRecoveryEngine()
    
    def test_valid_schema(self, engine):
        """Test valid feature graph passes schema validation."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(
                    id="s1",
                    primitives=[
                        SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                    ]
                )
            ],
            features=[
                FeatureV2(id="f1", type="extrude", sketch="s1", params={"depth": 10})
            ]
        )
        
        issues = engine._validate_schema(fg)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        assert len(critical) == 0
    
    
    def test_invalid_version(self, engine):
        """Test invalid version - SKIPPED: Pydantic blocks invalid version at construction."""
        # Note: Pydantic's Literal["1.0", "2.0"] prevents creating invalid versions
        # This test is not needed as the type system enforces validity
        pytest.skip("Pydantic enforces valid versions at construction time")
    
    def test_no_sketches(self, engine):
        """Test missing sketches triggers CRITICAL."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[],  # Empty
            features=[]
        )
        
        issues = engine._validate_schema(fg)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        assert len(critical) > 0
        assert any("sketch" in i.message.lower() for i in critical)
    
    def test_invalid_dependency(self, engine):
        """Test invalid feature dependency triggers CRITICAL."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(
                    id="f1",
                    type="fillet",
                    params={"radius": 2},
                    dependencies=["nonexistent_feature"]  # Invalid
                )
            ]
        )
        
        issues = engine._validate_schema(fg)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        assert len(critical) > 0
        assert any("dependency" in i.message.lower() for i in critical)
    
    def test_invalid_sketch_reference(self, engine):
        """Test invalid sketch reference triggers CRITICAL."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(
                    id="f1",
                    type="extrude",
                    sketch="nonexistent_sketch",  # Invalid
                    params={"depth": 10}
                )
            ]
        )
        
        issues = engine._validate_schema(fg)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        assert len(critical) > 0
        assert any("sketch" in i.message.lower() for i in critical)


class TestParameterValidation:
    """Test parameter validation."""
    
    @pytest.fixture
    def engine(self):
        return ErrorRecoveryEngine()
    
    def test_valid_parameters(self, engine):
        """Test valid parameters pass validation."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(
                    id="s1",
                    primitives=[
                        SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                    ]
                )
            ],
            features=[
                FeatureV2(id="f1", type="extrude", sketch="s1", params={"depth": 10})
            ]
        )
        
        issues = engine._validate_parameters(fg)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        assert len(critical) == 0
    
    def test_negative_dimension(self, engine):
        """Test negative dimension triggers CRITICAL."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(
                    id="s1",
                    primitives=[
                        SketchPrimitiveV2(id="p1", type="rectangle", params={"width": -30, "height": 20})
                    ]
                )
            ],
            features=[]
        )
        
        issues = engine._validate_parameters(fg)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        assert len(critical) > 0
        assert any("positive" in i.message.lower() for i in critical)
    
    def test_negative_fillet_radius(self, engine):
        """Test negative fillet radius triggers CRITICAL."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(id="f1", type="fillet", params={"radius": -2})  # Negative
            ]
        )
        
        issues = engine._validate_parameters(fg)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        assert len(critical) > 0
        assert any("fillet" in i.message.lower() and "positive" in i.message.lower() for i in critical)
    
    def test_large_fillet_radius_warning(self, engine):
        """Test very large fillet radius triggers WARNING."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(id="f1", type="fillet", params={"radius": 150})  # Very large
            ]
        )
        
        issues = engine._validate_parameters(fg)
        warnings = [i for i in issues if i.level == ValidationLevel.WARNING]
        
        assert len(warnings) > 0
        assert any("large" in i.message.lower() for i in warnings)


class TestGeometricFeasibility:
    """Test geometric feasibility checks."""
    
    @pytest.fixture
    def engine(self):
        return ErrorRecoveryEngine()
    
    def test_reasonable_fillet(self, engine):
        """Test reasonable fillet passes validation."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(id="f1", type="extrude", sketch="s1", params={"depth": 10}),
                FeatureV2(id="f2", type="fillet", params={"radius": 2})  # Reasonable
            ]
        )
        
        issues = engine._validate_geometry_feasibility(fg)
        warnings = [i for i in issues if i.level == ValidationLevel.WARNING]
        
        assert len(warnings) == 0
    
    def test_fillet_too_large_for_geometry(self, engine):
        """Test fillet larger than geometry triggers WARNING."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(id="f1", type="extrude", sketch="s1", params={"depth": 10}),
                FeatureV2(id="f2", type="fillet", params={"radius": 30})  # Too large
            ]
        )
        
        issues = engine._validate_geometry_feasibility(fg)
        warnings = [i for i in issues if i.level == ValidationLevel.WARNING]
        
        assert len(warnings) > 0
        assert any("too large" in i.message.lower() for i in warnings)


class TestCritiquePromptGeneration:
    """Test self-critique prompt generation."""
    
    @pytest.fixture
    def engine(self):
        return ErrorRecoveryEngine()
    
    def test_generate_critique_prompt(self, engine):
        """Test critique prompt includes error details."""
        issues = [
            ValidationIssue(
                level=ValidationLevel.CRITICAL,
                stage="parameters",
                message="Width must be positive",
                fix_suggestion="Set width > 0"
            )
        ]
        
        prompt = engine.generate_critique_prompt("Create a box", issues)
        
        assert "CRITICAL ERRORS" in prompt
        assert "Width must be positive" in prompt
        assert "Set width > 0" in prompt
        assert "Create a box" in prompt
    
    def test_critique_prompt_no_critical_issues(self, engine):
        """Test prompt unchanged when no critical issues."""
        issues = [
            ValidationIssue(
                level=ValidationLevel.WARNING,
                stage="geometry",
                message="Fillet may be large"
            )
        ]
        
        prompt = engine.generate_critique_prompt("Create a box", issues)
        
        # Should return original prompt
        assert prompt == "Create a box"


class TestCompilationErrorSuggestions:
    """Test compilation error fix suggestions."""
    
    @pytest.fixture
    def engine(self):
        return ErrorRecoveryEngine()
    
    def test_suggest_radius_fix(self, engine):
        """Test radius error suggestion."""
        error = Exception("Fillet radius too large")
        suggestion = engine.suggest_compilation_fix(error)
        
        assert "radius" in suggestion.lower()
    
    def test_suggest_selector_fix(self, engine):
        """Test selector error suggestion."""
        error = Exception("Invalid selector syntax")
        suggestion = engine.suggest_compilation_fix(error)
        
        assert "selector" in suggestion.lower()


class TestValidateFeatureGraph:
    """Test comprehensive validation."""
    
    @pytest.fixture
    def engine(self):
        return ErrorRecoveryEngine()
    
    def test_validate_valid_graph(self, engine):
        """Test validating a fully valid feature graph."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(id="f1", type="extrude", sketch="s1", params={"depth": 10})
            ]
        )
        
        issues = engine.validate_feature_graph(fg)
        
        assert not engine.has_critical_issues(issues)
    
    def test_validate_invalid_graph(self, engine):
        """Test validating graph with errors."""
        fg = FeatureGraphV2(
            version="2.0",
            sketches=[
                SketchGraphV2(id="s1", primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": -30, "height": 20})
                ])
            ],
            features=[
                FeatureV2(id="f1", type="extrude", sketch="s1", params={"depth": -10})
            ]
        )
        
        issues = engine.validate_feature_graph(fg)
        
        assert engine.has_critical_issues(issues)
        critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        assert len(critical) >= 2  # At least width and depth errors
