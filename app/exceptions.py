"""
Structured Exception Hierarchy for OrionFlow_CAD.

Provides typed exceptions with error codes for consistent error handling
across the application. All exceptions include:
- Error code for programmatic handling
- User-friendly message
- Retryable flag for client-side retry logic
- Optional details for debugging

Usage:
    from app.exceptions import LLMGenerationError, CompilationError
    
    raise LLMGenerationError(
        message="Failed to parse LLM response",
        details={"raw_response": response[:100]}
    )
"""
from enum import Enum
from typing import Optional, Dict, Any


class ErrorCode(str, Enum):
    """Standardized error codes for API responses."""
    
    # Validation Errors (400)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_PROMPT = "INVALID_PROMPT"
    INVALID_FEATURE_GRAPH = "INVALID_FEATURE_GRAPH"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    
    # LLM Errors (500, potentially retryable)
    LLM_GENERATION_FAILED = "LLM_GENERATION_FAILED"
    LLM_PARSE_ERROR = "LLM_PARSE_ERROR"
    LLM_SCHEMA_VALIDATION_FAILED = "LLM_SCHEMA_VALIDATION_FAILED"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_API_KEY_INVALID = "LLM_API_KEY_INVALID"
    
    # Compilation Errors (500)
    COMPILATION_FAILED = "COMPILATION_FAILED"
    DIMENSION_CONFLICT = "DIMENSION_CONFLICT"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"
    CONSTRAINT_CONFLICT = "CONSTRAINT_CONFLICT"
    TOPOLOGY_ERROR = "TOPOLOGY_ERROR"
    
    # Export Errors (500)
    EXPORT_FAILED = "EXPORT_FAILED"
    FILE_WRITE_ERROR = "FILE_WRITE_ERROR"
    
    # External Service Errors (502/503)
    ONSHAPE_SYNC_FAILED = "ONSHAPE_SYNC_FAILED"
    EXTERNAL_SERVICE_UNAVAILABLE = "EXTERNAL_SERVICE_UNAVAILABLE"
    
    # System Errors (500)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class OrionFlowError(Exception):
    """
    Base exception for all OrionFlow errors.
    
    All application exceptions should inherit from this class.
    
    Attributes:
        message: Human-readable error message
        code: Standardized error code
        retryable: Whether the client should retry
        details: Additional context for debugging
        status_code: HTTP status code to return
    """
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.details = details or {}
        self.status_code = status_code
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to API response format."""
        response = {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "retryable": self.retryable
            }
        }
        if self.details:
            response["error"]["details"] = self.details
        return response


# =============================================================================
# Validation Errors (HTTP 400)
# =============================================================================

class ValidationError(OrionFlowError):
    """Raised when input validation fails."""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            code=code,
            retryable=False,
            details=details,
            status_code=400
        )


class InvalidPromptError(ValidationError):
    """Raised when the user prompt is invalid or empty."""
    
    def __init__(self, message: str = "Invalid or empty prompt", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=ErrorCode.INVALID_PROMPT,
            details=details
        )


class InvalidFeatureGraphError(ValidationError):
    """Raised when the feature graph structure is invalid."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=ErrorCode.INVALID_FEATURE_GRAPH,
            details=details
        )


class UnsupportedOperationError(ValidationError):
    """Raised when an unsupported CAD operation is requested."""
    
    def __init__(self, operations: list, message: str = None):
        msg = message or f"Unsupported operations requested: {', '.join(operations)}"
        super().__init__(
            message=msg,
            code=ErrorCode.UNSUPPORTED_OPERATION,
            details={"unsupported_operations": operations}
        )


# =============================================================================
# LLM Errors (HTTP 500, some retryable)
# =============================================================================

class LLMError(OrionFlowError):
    """Base class for LLM-related errors."""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.LLM_GENERATION_FAILED,
        retryable: bool = True,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            code=code,
            retryable=retryable,
            details=details,
            status_code=500
        )


class LLMGenerationError(LLMError):
    """Raised when LLM fails to generate a valid response."""
    
    def __init__(self, message: str = "LLM generation failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=ErrorCode.LLM_GENERATION_FAILED,
            retryable=True,
            details=details
        )


class LLMParseError(LLMError):
    """Raised when LLM response cannot be parsed as JSON."""
    
    def __init__(self, message: str = "Failed to parse LLM response as JSON", raw_response: str = None):
        details = {}
        if raw_response:
            details["raw_response_preview"] = raw_response[:200] if len(raw_response) > 200 else raw_response
        super().__init__(
            message=message,
            code=ErrorCode.LLM_PARSE_ERROR,
            retryable=True,
            details=details
        )


class LLMSchemaValidationError(LLMError):
    """Raised when LLM output fails schema validation."""
    
    def __init__(self, message: str, validation_errors: list = None):
        super().__init__(
            message=message,
            code=ErrorCode.LLM_SCHEMA_VALIDATION_FAILED,
            retryable=True,
            details={"validation_errors": validation_errors or []}
        )


class LLMRateLimitError(LLMError):
    """Raised when LLM API rate limit is exceeded."""
    
    def __init__(self, retry_after: int = None):
        message = "LLM API rate limit exceeded"
        if retry_after:
            message += f". Retry after {retry_after} seconds."
        super().__init__(
            message=message,
            code=ErrorCode.LLM_RATE_LIMITED,
            retryable=True,
            details={"retry_after_seconds": retry_after}
        )


class LLMAPIKeyError(LLMError):
    """Raised when LLM API key is missing or invalid."""
    
    def __init__(self, provider: str = "unknown"):
        super().__init__(
            message=f"Invalid or missing API key for {provider}. Check your .env configuration.",
            code=ErrorCode.LLM_API_KEY_INVALID,
            retryable=False,
            details={"provider": provider}
        )


# =============================================================================
# Compilation Errors (HTTP 500)
# =============================================================================

class CompilationError(OrionFlowError):
    """Base class for CAD compilation errors."""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.COMPILATION_FAILED,
        retryable: bool = True,
        details: Optional[Dict[str, Any]] = None,
        failed_feature: str = None
    ):
        if failed_feature:
            details = details or {}
            details["failed_feature"] = failed_feature
        super().__init__(
            message=message,
            code=code,
            retryable=retryable,
            details=details,
            status_code=500
        )


class DimensionConflictError(CompilationError):
    """Raised when dimensions conflict or are out of range."""
    
    def __init__(self, message: str, dimension: str = None, value: float = None, constraint: str = None):
        details = {}
        if dimension:
            details["dimension"] = dimension
        if value is not None:
            details["value"] = value
        if constraint:
            details["constraint"] = constraint
        super().__init__(
            message=message,
            code=ErrorCode.DIMENSION_CONFLICT,
            retryable=True,
            details=details
        )


class GeometryError(CompilationError):
    """Raised when geometry cannot be constructed."""
    
    def __init__(self, message: str, operation: str = None):
        super().__init__(
            message=message,
            code=ErrorCode.GEOMETRY_INVALID,
            retryable=True,
            details={"operation": operation} if operation else None
        )


class ConstraintConflictError(CompilationError):
    """Raised when sketch constraints conflict."""
    
    def __init__(self, message: str, conflicting_constraints: list = None):
        super().__init__(
            message=message,
            code=ErrorCode.CONSTRAINT_CONFLICT,
            retryable=True,
            details={"conflicting_constraints": conflicting_constraints or []}
        )


class TopologyError(CompilationError):
    """Raised when topology selection fails."""
    
    def __init__(self, message: str, selector: str = None):
        super().__init__(
            message=message,
            code=ErrorCode.TOPOLOGY_ERROR,
            retryable=True,
            details={"selector": selector} if selector else None
        )


# =============================================================================
# Export Errors (HTTP 500)
# =============================================================================

class ExportError(OrionFlowError):
    """Raised when file export fails."""
    
    def __init__(self, message: str, file_path: str = None, format: str = None):
        details = {}
        if file_path:
            details["file_path"] = str(file_path)
        if format:
            details["format"] = format
        super().__init__(
            message=message,
            code=ErrorCode.EXPORT_FAILED,
            retryable=False,
            details=details,
            status_code=500
        )


# =============================================================================
# External Service Errors (HTTP 502/503)
# =============================================================================

class OnshapeSyncError(OrionFlowError):
    """Raised when Onshape synchronization fails."""
    
    def __init__(self, message: str = "Failed to sync with Onshape", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code=ErrorCode.ONSHAPE_SYNC_FAILED,
            retryable=True,
            details=details,
            status_code=502
        )


class ExternalServiceError(OrionFlowError):
    """Raised when an external service is unavailable."""
    
    def __init__(self, service: str, message: str = None):
        msg = message or f"External service '{service}' is unavailable"
        super().__init__(
            message=msg,
            code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
            retryable=True,
            details={"service": service},
            status_code=503
        )


# =============================================================================
# Configuration Errors
# =============================================================================

class ConfigurationError(OrionFlowError):
    """Raised when application configuration is invalid."""
    
    def __init__(self, message: str, config_key: str = None):
        super().__init__(
            message=message,
            code=ErrorCode.CONFIGURATION_ERROR,
            retryable=False,
            details={"config_key": config_key} if config_key else None,
            status_code=500
        )
