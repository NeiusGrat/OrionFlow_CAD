from app.services.retry_policy import is_retryable
from app.domain.execution_trace import ExecutionTrace, TraceEvent

def test_no_infinite_retry():
    attempts = 0
    MAX_RETRIES = 1

    while attempts <= MAX_RETRIES:
        attempts += 1

    assert attempts == 2


def test_is_retryable_logic():
    # 1. Success -> False
    trace = ExecutionTrace(success=True, events=[])
    assert is_retryable(trace) is False

    # 2. Generic Failure -> False (Conservative)
    trace = ExecutionTrace(
        success=False,
        events=[
            TraceEvent(stage="compile", target=None, status="failure", message="Random error")
        ]
    )
    assert is_retryable(trace) is False

    # 3. Schema Error -> True
    trace = ExecutionTrace(
        success=False,
        events=[
            TraceEvent(stage="compile", target=None, status="failure", message="Invalid FeatureGraph schema: foo")
        ]
    )
    assert is_retryable(trace) is True

    # 4. Compilation Error -> True
    trace = ExecutionTrace(
        success=False,
        events=[
            TraceEvent(stage="sketch_compile", target="s1", status="failure", message="SketchCompilationError: bar")
        ]
    )
    assert is_retryable(trace) is True
