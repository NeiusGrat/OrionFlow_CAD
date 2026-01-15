"""
Error Recovery Engine - Production-grade validation and retry system.

VERSION 0.5: Multi-stage validation with LLM self-critique.

Features:
- Pre-compilation validation (schema, parameters, geometry)
- Progressive retry strategies
- LLM self-critique with error context
- Severity-based issue classification
"""
from dataclasses import dataclass
from typing import List, Optional, Any, Tuple
from enum import Enum
from pathlib import Path
import logging

from app.domain.feature_graph_v2 import FeatureGraphV2

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """Validation severity levels."""
    CRITICAL = "critical"  # Must fix, blocks compilation
    WARNING = "warning"    # Should fix, may cause issues
    INFO = "info"          # Optional improvement


@dataclass
class ValidationIssue:
    """
    Single validation issue.
    
    Attributes:
        level: Severity (CRITICAL/WARNING/INFO)
        stage: Validation stage (schema/parameters/geometry/compilation)
        message: Human-readable description
        fix_suggestion: Optional fix recommendation
        can_auto_fix: Whether issue can be auto-corrected
    """
    level: ValidationLevel
    stage: str
    message: str
    fix_suggestion: Optional[str] = None
    can_auto_fix: bool = False


class ErrorRecoveryEngine:
    """
    Multi-stage error recovery with self-critique.
    
    Validation pipeline:
    1. Schema validation
    2. Parameter validation
    3. Geometric feasibility
    4. Compilation attempt
    5. Self-critique retry on failure
    """
    
    def __init__(self, max_retries: int = 3):
        """
        Initialize error recovery engine.
        
        Args:
            max_retries: Maximum retry attempts (default: 3, up from 1)
        """
        self.max_retries = max_retries
        logger.info(f"ErrorRecoveryEngine initialized with max_retries={max_retries}")
    
    def validate_feature_graph(
        self,
        feature_graph: FeatureGraphV2
    ) -> List[ValidationIssue]:
        """
        Comprehensive validation without compilation.
        
        Args:
            feature_graph: FeatureGraph to validate
            
        Returns:
            List of validation issues
        """
        issues = []
        
        # Stage 1: Schema validation
        issues.extend(self._validate_schema(feature_graph))
        
        # Stage 2: Parameter validation
        issues.extend(self._validate_parameters(feature_graph))
        
        # Stage 3: Geometric feasibility
        issues.extend(self._validate_geometry_feasibility(feature_graph))
        
        return issues
    
    def has_critical_issues(self, issues: List[ValidationIssue]) -> bool:
        """Check if any issues are CRITICAL."""
        return any(i.level == ValidationLevel.CRITICAL for i in issues)
    
    def _validate_schema(self, fg: FeatureGraphV2) -> List[ValidationIssue]:
        """
        Validate JSON schema compliance.
        
        Checks:
        - Version field
        - Required fields (sketches, features)
        - Feature dependency validity
        """
        issues = []
        
        # Check version
        if fg.version not in ["1.0", "2.0"]:
            issues.append(ValidationIssue(
                level=ValidationLevel.CRITICAL,
                stage="schema",
                message=f"Invalid version: {fg.version}",
                fix_suggestion="Use version '2.0' for V2 features"
            ))
        
        # Check required fields
        if not fg.sketches:
            issues.append(ValidationIssue(
                level=ValidationLevel.CRITICAL,
                stage="schema",
                message="No sketches defined",
                fix_suggestion="Add at least one sketch with primitives"
            ))
        
        if not fg.features:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                stage="schema",
                message="No features defined",
                fix_suggestion="Add extrude or other 3D features"
            ))
        
        # Validate feature dependencies
        feature_ids = {f.id for f in fg.features}
        for feature in fg.features:
            deps = getattr(feature, "dependencies", [])
            for dep in deps:
                if dep not in feature_ids:
                    issues.append(ValidationIssue(
                        level=ValidationLevel.CRITICAL,
                        stage="schema",
                        message=f"Feature {feature.id}: Invalid dependency '{dep}'",
                        fix_suggestion=f"Remove dependency or add feature with id='{dep}'"
                    ))
        
        # Validate sketch references
        sketch_ids = {s.id for s in fg.sketches}
        for feature in fg.features:
            sketch_ref = getattr(feature, "sketch", None)
            if sketch_ref and sketch_ref not in sketch_ids:
                issues.append(ValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    stage="schema",
                    message=f"Feature {feature.id}: Invalid sketch reference '{sketch_ref}'",
                    fix_suggestion=f"Use existing sketch id from: {sketch_ids}"
                ))
        
        return issues
    
    def _validate_parameters(self, fg: FeatureGraphV2) -> List[ValidationIssue]:
        """
        Validate parameter bounds and consistency.
        
        Checks:
        - Positive dimensions (width, height, radius)
        - Reasonable fillet radii
        - Positive extrude distances
        """
        issues = []
        
        # Validate sketch primitives
        for sketch in fg.sketches:
            for primitive in sketch.primitives:
                params = getattr(primitive, "params", {})
                
                # Check positive dimensions
                for key in ["width", "height", "radius", "length"]:
                    if key in params:
                        value = params[key]
                        
                        # Try to resolve if it's a string reference
                        if isinstance(value, str):
                            continue  # Skip parameter references like "$width"
                        
                        if not isinstance(value, (int, float)):
                            issues.append(ValidationIssue(
                                level=ValidationLevel.CRITICAL,
                                stage="parameters",
                                message=f"Sketch {sketch.id}, primitive {primitive.id}: {key} must be numeric, got {type(value).__name__}",
                                fix_suggestion=f"Set {key} to a positive number"
                            ))
                        elif value <= 0:
                            issues.append(ValidationIssue(
                                level=ValidationLevel.CRITICAL,
                                stage="parameters",
                                message=f"Sketch {sketch.id}, primitive {primitive.id}: {key}={value} (must be positive)",
                                fix_suggestion=f"Set {key} to a positive number"
                            ))
        
        # Validate feature parameters
        for feature in fg.features:
            params = getattr(feature, "params", {})
            
            # Fillet radius constraints
            if feature.type == "fillet":
                radius = params.get("radius")
                if radius is not None:
                    if isinstance(radius, str):
                        continue  # Parameter reference
                    
                    if radius <= 0:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.CRITICAL,
                            stage="parameters",
                            message=f"Feature {feature.id}: Fillet radius must be positive, got {radius}",
                            fix_suggestion="Use positive radius value"
                        ))
                    
                    # Warn if radius seems very large
                    if radius > 100:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.WARNING,
                            stage="parameters",
                            message=f"Feature {feature.id}: Fillet radius very large ({radius}mm)",
                            fix_suggestion="Consider reducing radius to avoid failures"
                        ))
            
            # Extrude distance
            if feature.type == "extrude":
                distance = params.get("distance") or params.get("depth")
                if distance is not None:
                    if isinstance(distance, str):
                        continue  # Parameter reference
                    
                    if distance <= 0:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.CRITICAL,
                            stage="parameters",
                            message=f"Feature {feature.id}: Extrude distance must be positive, got {distance}",
                            fix_suggestion="Use positive distance/depth value"
                        ))
            
            # Chamfer distance
            if feature.type == "chamfer":
                distance = params.get("distance")
                if distance is not None:
                    if isinstance(distance, str):
                        continue
                    
                    if distance <= 0:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.CRITICAL,
                            stage="parameters",
                            message=f"Feature {feature.id}: Chamfer distance must be positive, got {distance}",
                            fix_suggestion="Use positive distance value"
                        ))
        
        return issues
    
    def _validate_geometry_feasibility(self, fg: FeatureGraphV2) -> List[ValidationIssue]:
        """
        Check geometric feasibility without full compilation.
        
        Heuristic checks:
        - Fillet radius vs edge length estimates
        - Dimension ratios
        """
        issues = []
        
        # Extract dimensions from sketches
        dimensions = self._extract_dimensions(fg)
        
        if not dimensions:
            return issues
        
        min_dim = min(dimensions)
        
        # Check fillet radii against geometry size
        for feature in fg.features:
            if feature.type == "fillet":
                params = getattr(feature, "params", {})
                radius = params.get("radius")
                
                if radius is None or isinstance(radius, str):
                    continue
                
                # Conservative heuristic: radius should be < min_dimension / 2
                if radius > min_dim / 2:
                    issues.append(ValidationIssue(
                        level=ValidationLevel.WARNING,
                        stage="geometry",
                        message=f"Feature {feature.id}: Fillet radius {radius} may be too large for geometry (min dimension: {min_dim})",
                        fix_suggestion=f"Try radius < {min_dim / 3:.1f}"
                    ))
        
        return issues
    
    def _extract_dimensions(self, fg: FeatureGraphV2) -> List[float]:
        """Extract all dimensional values from feature graph."""
        dims = []
        
        for sketch in fg.sketches:
            for primitive in sketch.primitives:
                params = getattr(primitive, "params", {})
                
                for key in ["width", "height", "radius", "length"]:
                    if key in params:
                        value = params[key]
                        if isinstance(value, (int, float)):
                            dims.append(float(value))
        
        return dims
    
    def generate_critique_prompt(
        self,
        original_prompt: str,
        issues: List[ValidationIssue]
    ) -> str:
        """
        Generate self-critique prompt for LLM retry.
        
        Args:
            original_prompt: Original user prompt
            issues: List of validation issues
            
        Returns:
            Formatted critique prompt
        """
        # Filter to CRITICAL issues only
        critical_issues = [i for i in issues if i.level == ValidationLevel.CRITICAL]
        
        if not critical_issues:
            return original_prompt
        
        # Build error summary
        error_lines = []
        for issue in critical_issues:
            error_lines.append(f"- {issue.stage.upper()}: {issue.message}")
            if issue.fix_suggestion:
                error_lines.append(f"  → Fix: {issue.fix_suggestion}")
        
        error_summary = "\n".join(error_lines)
        
        # Create critique prompt
        critique = f"""
⚠️ PREVIOUS GENERATION HAD CRITICAL ERRORS:

{error_summary}

Original user request: {original_prompt}

Generate a CORRECTED FeatureGraphV2 that fixes ALL the errors above.

Common fixes:
1. Ensure all numeric parameters are positive (width, height, radius, depth > 0)
2. Use valid feature types: extrude, fillet, chamfer, revolve
3. Check fillet radius is reasonable (< half of smallest dimension)
4. Verify all feature dependencies reference existing features
5. Ensure all sketch references are valid

Output ONLY the corrected JSON FeatureGraph (version 2.0).
"""
        
        return critique
    
    def suggest_compilation_fix(self, error: Exception) -> str:
        """
        Suggest fix for compilation errors.
        
        Args:
            error: Exception from compilation
            
        Returns:
            Human-readable fix suggestion
        """
        error_str = str(error).lower()
        
        if "radius" in error_str:
            return "Reduce fillet/chamfer radius - it may be too large for the geometry"
        elif "selector" in error_str or "topology" in error_str:
            return "Use valid Build123d selector (>Z for top, |X for parallel to X)"
        elif "sketch" in error_str:
            return "Ensure sketch is properly defined and referenced in feature"
        elif "extrude" in error_str:
            return "Check extrude distance is positive and reasonable"
        elif "distance" in error_str or "depth" in error_str:
            return "Ensure distance/depth parameter is positive"
        else:
            return "Review feature parameters and geometry constraints"
