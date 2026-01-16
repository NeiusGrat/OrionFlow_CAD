from app.domain.execution_trace import ExecutionTrace


def is_retryable(trace: ExecutionTrace) -> bool:
    """
    Determines whether a failed execution is safe to retry.
    
    Retryable errors include:
    - Schema validation errors
    - Sketch/Feature compilation errors
    - Geometry validation errors (invalid/non-manifold/zero-volume)
    """
    if trace.success:
        return False

    for event in trace.events:
        if event.status == "failure":
            # Schema and compiler errors are retryable
            if "Invalid FeatureGraph" in (event.message or ""):
                return True
            if "SketchCompilationError" in (event.message or ""):
                return True
            if "FeatureCompilationError" in (event.message or ""):
                return True
            
            # Geometry validation errors are retryable (Agentic Self-Correction)
            if event.stage == "geometry_validation":
                return True
            if "GEOMETRY VALIDATION FAILED" in (event.message or ""):
                return True

    return False
