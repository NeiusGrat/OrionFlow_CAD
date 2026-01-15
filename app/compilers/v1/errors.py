"""Compiler error exceptions.

Phase 3: Extended with structured error support for machine-readable feedback.
"""


class CompilerError(Exception):
    """Base compiler error."""
    pass


class SketchCompilationError(CompilerError):
    """Raised when sketch compilation fails."""
    pass


class FeatureCompilationError(CompilerError):
    """
    Raised when feature compilation fails.
    
    Can optionally attach a structured CompilerError (from app.domain.compiler_errors)
    for machine-readable feedback to LLM retry logic.
    """
    def __init__(self, message: str, compiler_error=None):
        super().__init__(message)
        self.compiler_error = compiler_error  # Optional structured error from validators
