from app.domain.dataset_sample import DatasetSample
from app.services.dataset_writer import write_dataset_sample
from app.domain.execution_trace import ExecutionTrace, TraceEvent
from app.domain.feature_graph_v1 import FeatureGraphV1
import os
import shutil

def test_dataset_write():
    # Clean up test output if needed
    test_dir = "data/dataset"
    
    sample = DatasetSample(
        prompt="test_prompt_logging",
        decomposed_intent={},
        feature_graph=FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={},
            parameters={},
            sketches=[],
            features=[]
        ),
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
