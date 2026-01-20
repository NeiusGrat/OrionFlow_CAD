"""
Tests for Training Data Writer Service (Step 6).

Tests the JSONL persistence of training samples.
"""
import pytest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.training_sample import TrainingSample, GeometryMetrics
from app.services.training_writer import TrainingDataWriter


class TestTrainingDataWriter:
    """Test TrainingDataWriter class."""
    
    @pytest.fixture
    def writer(self):
        """Create writer with temp directory."""
        with TemporaryDirectory() as tmpdir:
            yield TrainingDataWriter(root_dir=Path(tmpdir), version="test_v1")
    
    def test_write_success_sample(self, writer):
        """Test writing a successful sample."""
        sample = TrainingSample(
            prompt="Create a box 30x20x10",
            construction_plan={"steps": ["sketch", "extrude"]},
            feature_graph={"version": "1.0", "sketches": [], "features": []},
            compile_success=True,
            geometry_metrics=GeometryMetrics(
                volume=6000.0,
                surface_area=2200.0,
                bounding_box={},
                is_valid=True,
                is_manifold=True
            )
        )
        
        path = writer.write_sample(sample)
        
        assert path.exists()
        assert "success" in str(path)
        assert path.suffix == ".jsonl"
    
    def test_write_failure_sample(self, writer):
        """Test writing a failed sample."""
        sample = TrainingSample(
            prompt="Create something impossible",
            construction_plan={},
            feature_graph={},
            compile_success=False,
            compile_error="Compilation failed"
        )
        
        path = writer.write_sample(sample)
        
        assert path.exists()
        assert "failure" in str(path)
    
    def test_training_pair_written_for_success(self, writer):
        """Test that training pairs are written for successful samples."""
        sample = TrainingSample(
            prompt="Create a cylinder",
            construction_plan={"steps": ["circle", "extrude"]},
            feature_graph={"version": "1.0", "features": [{"type": "extrude"}]},
            compile_success=True
        )
        
        pairs_path = writer.write_training_pair(sample)
        
        assert pairs_path.exists()
        
        # Verify content
        with open(pairs_path, "r") as f:
            line = f.readline()
            data = json.loads(line)
            assert "prompt" in data
            assert "completion" in data
    
    def test_training_pair_not_written_for_failure(self, writer):
        """Test that training pairs are NOT written for failed samples."""
        sample = TrainingSample(
            prompt="Fail",
            construction_plan={},
            feature_graph={},
            compile_success=False
        )
        
        pairs_path = writer.write_training_pair(sample)
        
        assert pairs_path == Path("")
    
    def test_get_stats_empty(self, writer):
        """Test stats on empty dataset."""
        stats = writer.get_stats()
        
        assert stats["total_count"] == 0
        assert stats["success_count"] == 0
        assert stats["failure_count"] == 0
    
    def test_get_stats_with_samples(self, writer):
        """Test stats with samples."""
        # Write 2 success, 1 failure
        for i in range(2):
            writer.write_sample(TrainingSample(
                prompt=f"Success {i}",
                construction_plan={},
                feature_graph={},
                compile_success=True
            ))
        
        writer.write_sample(TrainingSample(
            prompt="Failure",
            construction_plan={},
            feature_graph={},
            compile_success=False
        ))
        
        stats = writer.get_stats()
        
        assert stats["total_count"] == 3
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert stats["success_rate"] == pytest.approx(2/3)
    
    def test_load_samples(self, writer):
        """Test loading samples back."""
        # Write samples
        for i in range(3):
            writer.write_sample(TrainingSample(
                prompt=f"Prompt {i}",
                construction_plan={"index": i},
                feature_graph={},
                compile_success=True
            ))
        
        # Load all
        samples = writer.load_samples()
        
        assert len(samples) == 3
        assert all(s.compile_success for s in samples)
    
    def test_load_samples_success_only(self, writer):
        """Test loading only successful samples."""
        writer.write_sample(TrainingSample(
            prompt="Success",
            construction_plan={},
            feature_graph={},
            compile_success=True
        ))
        
        writer.write_sample(TrainingSample(
            prompt="Failure",
            construction_plan={},
            feature_graph={},
            compile_success=False
        ))
        
        samples = writer.load_samples(success_only=True)
        
        assert len(samples) == 1
        assert samples[0].prompt == "Success"
    
    def test_load_samples_with_limit(self, writer):
        """Test loading with limit."""
        for i in range(10):
            writer.write_sample(TrainingSample(
                prompt=f"Prompt {i}",
                construction_plan={},
                feature_graph={},
                compile_success=True
            ))
        
        samples = writer.load_samples(limit=3)
        
        assert len(samples) == 3
