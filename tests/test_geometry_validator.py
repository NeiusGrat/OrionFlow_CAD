"""
Tests for Geometry Validator (Agentic Self-Correction Loop).

Tests post-compilation geometry validation.
"""
import pytest

from app.validation.geometry_validator import (
    validate_solid,
    has_critical_geometry_issues,
    format_geometry_issues_for_llm,
    ValidationLevel,
    GeometryValidationIssue
)


class TestValidateSolid:
    """Test validate_solid function."""
    
    def test_none_solid_fails(self):
        """Test that None solid produces critical error."""
        issues = validate_solid(None)
        
        assert len(issues) == 1
        assert issues[0].level == ValidationLevel.CRITICAL
        assert issues[0].check == "null_check"
    
    def test_valid_solid_passes(self):
        """Test that a valid solid passes validation."""
        try:
            from build123d import Box
            solid = Box(10, 10, 10)
            
            issues = validate_solid(solid)
            critical = [i for i in issues if i.level == ValidationLevel.CRITICAL]
            
            assert len(critical) == 0
        except ImportError:
            pytest.skip("build123d not available")
    
    def test_small_volume_warning(self):
        """Test that very small volume produces warning."""
        try:
            from build123d import Box
            # Very small box: 0.1 x 0.1 x 0.1 = 0.001 mm³
            solid = Box(0.1, 0.1, 0.1)
            
            issues = validate_solid(solid)
            warnings = [i for i in issues if i.level == ValidationLevel.WARNING]
            
            # Should have a warning about small volume
            assert len(warnings) >= 1
            assert any("small volume" in i.message.lower() for i in warnings)
        except ImportError:
            pytest.skip("build123d not available")


class TestHasCriticalIssues:
    """Test has_critical_geometry_issues helper."""
    
    def test_no_issues_returns_false(self):
        """Empty list returns False."""
        assert has_critical_geometry_issues([]) is False
    
    def test_only_warnings_returns_false(self):
        """Warning-only list returns False."""
        issues = [
            GeometryValidationIssue(
                level=ValidationLevel.WARNING,
                check="volume",
                message="Small volume"
            )
        ]
        assert has_critical_geometry_issues(issues) is False
    
    def test_critical_issue_returns_true(self):
        """Critical issue returns True."""
        issues = [
            GeometryValidationIssue(
                level=ValidationLevel.CRITICAL,
                check="validity",
                message="Invalid BRep"
            )
        ]
        assert has_critical_geometry_issues(issues) is True


class TestFormatForLLM:
    """Test LLM prompt formatting."""
    
    def test_empty_issues_returns_empty(self):
        """No issues returns empty string."""
        result = format_geometry_issues_for_llm([])
        assert result == ""
    
    def test_formats_critical_issue(self):
        """Critical issues are formatted with details."""
        issues = [
            GeometryValidationIssue(
                level=ValidationLevel.CRITICAL,
                check="volume",
                message="Zero volume detected",
                fix_suggestion="Increase extrude depth"
            )
        ]
        
        result = format_geometry_issues_for_llm(issues)
        
        assert "GEOMETRY VALIDATION FAILED" in result
        assert "VOLUME" in result
        assert "Zero volume detected" in result
        assert "Increase extrude depth" in result
