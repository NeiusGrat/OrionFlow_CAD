from app.domain.dataset_sample import DatasetSample
from app.services.dataset_writer import write_dataset_sample
from app.domain.execution_trace import ExecutionTrace, TraceEvent
from app.domain.feature_graph_v3 import FeatureGraphV3
import os
import shutil

def test_dataset_write():
    # Clean up test output if needed
    test_dir = "data/dataset"
    
    sample = DatasetSample(
        prompt="test_prompt_logging",
        decomposed_intent={},
        # Minimal V3 graph; defaults are sufficient for serialization
        feature_graph=FeatureGraphV3(),
        execution_trace=ExecutionTrace(
            success=False,
            events=[TraceEvent(stage="test", target=None, status="failure", message="test failure")]
        ),
        success=False,
        backend="build123d",
        timestamp="2024-01-01T12:00:00.000000"
    )

    write_dataset_sample(sample)
    
    # Verify file exists
    # Timestamp : replaced by - in writer
    expected_filename = "2024-01-01T12-00-00.000000_test_prompt_logging.json"
    expected_path = os.path.join(test_dir, "failure", expected_filename)
    
    assert os.path.exists(expected_path)
    
    # Optional cleanup
    if os.path.exists(expected_path):
        os.remove(expected_path)
