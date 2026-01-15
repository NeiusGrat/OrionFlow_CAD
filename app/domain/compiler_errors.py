"""
Compiler Error System - Machine-Readable Error Reporting

Provides structured, explainable errors for geometry compilation failures.
Designed for LLM feedback loops and user debugging.

Key Features:
- Taxonomy of error types (InvalidFillet, ZeroThickness, etc.)
- Actionable error messages with suggested fixes
- Context data for debugging
- Integration with ExecutionTrace
"""
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ErrorType(str, Enum):
    """
    Taxonomy of compiler errors.
    
    Each error type represents a specific class of geometry failure
    that can be detected and explained.
    """
    # Parameter/Dimension Errors
    INVALID_PARAMETER = "InvalidParameter"
    ZERO_THICKNESS = "ZeroThickness"
    NEGATIVE_DIMENSION = "NegativeDimension"
    
    # Feature Errors
    INVALID_FILLET = "InvalidFillet"
    INVALID_CHAMFER = "InvalidChamfer"
    SKETCH_FAILURE = "SketchFailure"
    
    # Geometry Errors
    SELF_INTERSECTION = "SelfIntersection"
    DEGENERATE_FACE = "DegenerateFace"
    DEGENERATE_EDGE = "DegenerateEdge"
    TOPOLOGY_ERROR = "TopologyError"
    
    # Reference Errors
    MISSING_SKETCH = "MissingSketch"
    MISSING_FEATURE = "MissingFeature"
    CIRCULAR_DEPENDENCY = "CircularDependency"


class CompilerError(BaseModel):
    """
    Machine-readable compiler error.
    
    Designed for:
    - LLM feedback loops (retry with corrected parameters)
    - User debugging (clear explanation + suggested fix)
    - Automated testing (verify error detection)
    
    Example:
        >>> error = CompilerError(
        ...     error_type=ErrorType.INVALID_FILLET,
        ...     feature_id="fillet_2",
        ...     reason="Fillet radius 10mm exceeds edge length 8mm",
        ...     suggested_fix="Reduce radius to max 4mm (50% of edge length)",
        ...     context={"edge_length": 8.0, "requested_radius": 10.0}
        ... )
        >>> print(error.to_trace_message())
        Feature 'fillet_2': [InvalidFillet] Fillet radius 10mm exceeds edge length 8mm
    """
    error_type: ErrorType = Field(..., description="Classification of error")
    feature_id: Optional[str] = Field(None, description="Feature that caused the error")
    reason: str = Field(..., description="Human-readable explanation of what went wrong")
    suggested_fix: Optional[str] = Field(None, description="Actionable advice for fixing the error")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional debug data")
    
    def to_trace_message(self) -> str:
        """
        Format error for ExecutionTrace.message field.
        
        Returns:
            Formatted error string suitable for logging and display
        """
        # Handle error_type as both Enum and string (Pydantic may convert with use_enum_values)
        error_type_str = self.error_type.value if hasattr(self.error_type, 'value') else str(self.error_type)
        msg = f"[{error_type_str}] {self.reason}"
        if self.feature_id:
            msg = f"Feature '{self.feature_id}': {msg}"
        return msg
    
    def to_llm_feedback(self) -> str:
        """
        Format error for LLM retry feedback.
        
        Returns:
            Detailed error message with fix suggestion for LLM context
        """
        parts = [
            f"Error: {self.reason}",
        ]
        
        if self.suggested_fix:
            parts.append(f"Suggested fix: {self.suggested_fix}")
        
        if self.context:
            parts.append(f"Context: {self.context}")
        
        return "\n".join(parts)
    
    class Config:
        use_enum_values = True


class ValidationResult(BaseModel):
    """
    Result of a validation pass.
    
    Attributes:
        passed: Whether validation succeeded
        error: CompilerError if validation failed, None otherwise
        warnings: Non-fatal issues detected (future)
    """
    passed: bool
    error: Optional[CompilerError] = None
    warnings: list[str] = Field(default_factory=list)
    
    @classmethod
    def success(cls) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(passed=True)
    
    @classmethod
    def failure(cls, error: CompilerError) -> "ValidationResult":
        """Create a failed validation result."""
        return cls(passed=False, error=error)
