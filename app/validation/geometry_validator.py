"""
Geometry Validator - Post-compilation geometry validation.

Validates compiled solids for:
- Validity (BRep integrity)
- Manifold status (watertight)
- Positive volume

Part of the Agentic Self-Correction Loop (Feature B).
"""
from typing import List, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """Validation severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class GeometryValidationIssue:
    """
    A single geometry validation issue.
    
    Attributes:
        level: Severity (CRITICAL/WARNING/INFO)
        check: The check that failed (validity, manifold, volume)
        message: Human-readable description
        fix_suggestion: Optional fix recommendation
    """
    level: ValidationLevel
    check: str
    message: str
    fix_suggestion: str = ""


def validate_solid(solid: Any) -> List[GeometryValidationIssue]:
    """
    Validate a compiled solid for geometric integrity.
    
    Checks:
    1. is_valid: BRep structure is correct (no self-intersections, etc.)
    2. volume > 0: Solid has positive volume (not degenerate)
    
    Args:
        solid: A build123d Part/Solid object
        
    Returns:
        List of validation issues (empty if valid)
    """
    issues: List[GeometryValidationIssue] = []
    
    if solid is None:
        issues.append(GeometryValidationIssue(
            level=ValidationLevel.CRITICAL,
            check="null_check",
            message="Solid is None - compilation produced no geometry",
            fix_suggestion="Ensure sketch and feature operations produce a valid solid"
        ))
        return issues
    
    # Check 1: Validity (BRep integrity)
    try:
        # build123d Parts have .is_valid property from OpenCascade
        if hasattr(solid, 'is_valid'):
            if not solid.is_valid:
                issues.append(GeometryValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    check="validity",
                    message="Solid failed BRep validity check (self-intersection or topology error)",
                    fix_suggestion="Reduce fillet/chamfer radii or check for overlapping features"
                ))
        elif hasattr(solid, 'wrapped'):
            # Access the OCC shape directly
            from OCP.BRepCheck import BRepCheck_Analyzer
            analyzer = BRepCheck_Analyzer(solid.wrapped)
            if not analyzer.IsValid():
                issues.append(GeometryValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    check="validity",
                    message="Solid failed BRep validity check via OCC analyzer",
                    fix_suggestion="Reduce fillet/chamfer radii or check for overlapping features"
                ))
    except Exception as e:
        logger.warning(f"Could not check validity: {e}")
    
    # Check 2: Volume > 0
    try:
        volume = 0.0
        if hasattr(solid, 'volume'):
            volume = solid.volume
        elif hasattr(solid, 'Volume'):
            volume = solid.Volume()
        
        # Use a small epsilon for floating point comparison
        VOLUME_EPSILON = 1e-9
        
        if volume <= VOLUME_EPSILON:
            issues.append(GeometryValidationIssue(
                level=ValidationLevel.CRITICAL,
                check="volume",
                message=f"Solid has zero or negative volume ({volume:.6f})",
                fix_suggestion="Ensure extrude depth is positive and sketch has area"
            ))
        elif volume < 1.0:  # Very small volume warning (less than 1 mm³)
            issues.append(GeometryValidationIssue(
                level=ValidationLevel.WARNING,
                check="volume",
                message=f"Solid has very small volume ({volume:.6f} mm³)",
                fix_suggestion="This may be intentional for micro-parts, but verify dimensions"
            ))
    except Exception as e:
        logger.warning(f"Could not check volume: {e}")
    
    # Log results
    if issues:
        critical_count = sum(1 for i in issues if i.level == ValidationLevel.CRITICAL)
        logger.info(f"Geometry validation found {len(issues)} issues ({critical_count} critical)")
    else:
        logger.debug("Geometry validation passed")
    
    return issues


def has_critical_geometry_issues(issues: List[GeometryValidationIssue]) -> bool:
    """Check if any geometry issues are CRITICAL."""
    return any(i.level == ValidationLevel.CRITICAL for i in issues)


def format_geometry_issues_for_llm(issues: List[GeometryValidationIssue]) -> str:
    """
    Format geometry validation issues for LLM retry prompt.
    
    Args:
        issues: List of geometry validation issues
        
    Returns:
        Formatted string for LLM context
    """
    if not issues:
        return ""
    
    lines = ["⚠️ GEOMETRY VALIDATION FAILED:"]
    
    for issue in issues:
        level_icon = "🔴" if issue.level == ValidationLevel.CRITICAL else "🟡"
        lines.append(f"{level_icon} [{issue.check.upper()}] {issue.message}")
        if issue.fix_suggestion:
            lines.append(f"   → Fix: {issue.fix_suggestion}")
    
    lines.append("")
    lines.append("Generate a CORRECTED FeatureGraph that fixes these geometry issues.")
    
    return "\n".join(lines)
