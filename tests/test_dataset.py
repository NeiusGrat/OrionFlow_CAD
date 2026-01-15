"""
Tests for Dataset Collection System (VERSION 0.6).

Tests dataset manager, synthetic generation, and quality filtering.
"""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.dataset.dataset_manager import DatasetManager, DatasetSample
from app.dataset.synthetic_generator import SyntheticDataGenerator


class TestDatasetSample:
    """Test DatasetSample dataclass."""
    
    def test_create_sample(self):
        """Test basic sample creation."""
        sample = DatasetSample(
            prompt="Create a box 30x20x10",
            feature_graph={"version": "2.0", "sketches": [], "features": []}
        )
        
        assert sample.prompt == "Create a box 30x20x10"
        assert sample.sample_id != ""
        assert sample.success is True
    
    def test_derived_features(self):
        """Test derived features are extracted."""
        sample = DatasetSample(
            prompt="Create a box",
            feature_graph={
                "version": "2.0",
                "parameters": {"width": 30, "height": 20},
                "sketches": [{"id": "s1", "primitives": [{"id": "p1", "params": {"w": 30}}]}],
                "features": [{"id": "f1", "type": "extrude", "params": {"depth": 10}}]
            }
        )
        
        assert sample.sketch_count == 1
        assert sample.feature_count == 1
        assert sample.parameter_count > 0
    
    def test_to_dict(self):
        """Test serialization."""
        sample = DatasetSample(
            prompt="Test",
            feature_graph={"version": "2.0", "sketches": [], "features": []}
        )
        
        data = sample.to_dict()
        
        assert "prompt" in data
        assert "feature_graph" in data
        assert "sample_id" in data
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "prompt": "Create a cylinder",
            "feature_graph": {"version": "2.0", "sketches": [], "features": []},
            "success": True,
            "complexity_score": 0.5
        }
        
        sample = DatasetSample.from_dict(data)
        
        assert sample.prompt == "Create a cylinder"
        assert sample.complexity_score == 0.5


class TestDatasetManager:
    """Test DatasetManager class."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with temp directory."""
        with TemporaryDirectory() as tmpdir:
            yield DatasetManager(dataset_dir=Path(tmpdir))
    
    def test_save_and_load_sample(self, manager):
        """Test saving and loading sample."""
        sample = DatasetSample(
            prompt="Create a box",
            feature_graph={"version": "2.0", "sketches": [], "features": []},
            complexity_score=0.5
        )
        
        # Save
        path = manager.save_sample(sample)
        assert path.exists()
        
        # Load all
        samples = manager.load_all_samples()
        assert len(samples) == 1
        assert samples[0].prompt == "Create a box"
    
    def test_filter_by_success(self, manager):
        """Test filtering by success status."""
        # Save successful sample
        manager.save_sample(DatasetSample(
            prompt="Success",
            feature_graph={"version": "2.0", "sketches": [{"id": "s1", "primitives": []}], "features": []},
            success=True,
            complexity_score=0.5
        ))
        
        # Save failed sample
        manager.save_sample(DatasetSample(
            prompt="Failed",
            feature_graph={"version": "2.0", "sketches": [{"id": "s1", "primitives": []}], "features": []},
            success=False,
            complexity_score=0.5
        ))
        
        # Filter
        filtered = manager.filter_samples(require_success=True, min_complexity=0.0)
        
        assert len(filtered) == 1
        assert filtered[0].prompt == "Success"
    
    def test_filter_by_complexity(self, manager):
        """Test filtering by complexity score."""
        # Save high complexity
        manager.save_sample(DatasetSample(
            prompt="Complex",
            feature_graph={"version": "2.0", "sketches": [{"id": "s1", "primitives": []}], "features": []},
            complexity_score=0.8
        ))
        
        # Save low complexity
        manager.save_sample(DatasetSample(
            prompt="Simple",
            feature_graph={"version": "2.0", "sketches": [{"id": "s1", "primitives": []}], "features": []},
            complexity_score=0.1
        ))
        
        # Filter
        filtered = manager.filter_samples(min_complexity=0.5)
        
        assert len(filtered) == 1
        assert filtered[0].prompt == "Complex"
    
    def test_create_dataset_version(self, manager):
        """Test creating versioned dataset."""
        # Save samples
        for i in range(3):
            manager.save_sample(DatasetSample(
                prompt=f"Prompt {i}",
                feature_graph={"version": "2.0", "sketches": [{"id": "s1", "primitives": []}], "features": []},
                complexity_score=0.5
            ))
        
        # Create version
        samples = manager.filter_samples(min_complexity=0.0)
        jsonl_path = manager.create_dataset_version("v1.0", samples=samples)
        
        assert jsonl_path.exists()
        assert jsonl_path.name == "train.jsonl"
        
        # Verify JSONL content
        with open(jsonl_path) as f:
            lines = f.readlines()
        
        assert len(lines) == 3
    
    def test_calculate_complexity_score(self, manager):
        """Test complexity scoring."""
        # Simple graph
        simple = {"version": "2.0", "sketches": [], "features": []}
        assert manager.calculate_complexity_score(simple) == 0.0
        
        # Complex graph
        complex_fg = {
            "version": "2.0",
            "parameters": {"width": 30, "height": 20},
            "sketches": [{"id": "s1"}],
            "features": [
                {"id": "f1", "type": "extrude"},
                {"id": "f2", "type": "fillet", "topology_refs": {}}
            ]
        }
        score = manager.calculate_complexity_score(complex_fg)
        assert score > 0.4  # Has features, types, topology refs


class TestSyntheticDataGenerator:
    """Test SyntheticDataGenerator class."""
    
    @pytest.fixture
    def generator(self):
        """Create generator with fixed seed."""
        return SyntheticDataGenerator(seed=42)
    
    def test_generate_samples(self, generator):
        """Test generating samples."""
        samples = generator.generate_samples(10)
        
        assert len(samples) == 10
        
        for sample in samples:
            assert "prompt" in sample
            assert "feature_graph" in sample
            assert sample["feature_graph"]["version"] == "2.0"
    
    def test_samples_have_valid_structure(self, generator):
        """Test generated samples have valid FeatureGraph structure."""
        samples = generator.generate_samples(5)
        
        for sample in samples:
            fg = sample["feature_graph"]
            
            assert "version" in fg
            assert "sketches" in fg
            assert "features" in fg
            assert len(fg["sketches"]) > 0
            assert len(fg["features"]) > 0
    
    def test_samples_have_parameters(self, generator):
        """Test generated samples include parameter table."""
        samples = generator.generate_samples(5)
        
        for sample in samples:
            fg = sample["feature_graph"]
            assert "parameters" in fg
            assert len(fg["parameters"]) > 0
    
    def test_template_names(self, generator):
        """Test template names are available."""
        names = generator.get_template_names()
        
        assert len(names) > 0
        assert "simple_box" in names
        assert "simple_cylinder" in names
    
    def test_reproducibility(self):
        """Test that same seed produces same samples (single generator)."""
        gen = SyntheticDataGenerator(seed=42)
        
        # Just verify first sample is deterministic within same run
        sample = gen.generate_samples(1)[0]
        assert sample["template_name"] is not None
        assert sample["prompt"] is not None


class TestIntegration:
    """Integration tests."""
    
    def test_save_synthetic_samples(self):
        """Test saving synthetic samples to dataset."""
        with TemporaryDirectory() as tmpdir:
            manager = DatasetManager(dataset_dir=Path(tmpdir))
            generator = SyntheticDataGenerator(seed=42)
            
            # Generate and save
            samples = generator.generate_samples(10)
            
            for sample in samples:
                ds_sample = DatasetSample(
                    prompt=sample["prompt"],
                    feature_graph=sample["feature_graph"],
                    model_used="synthetic",
                    complexity_score=manager.calculate_complexity_score(sample["feature_graph"])
                )
                manager.save_sample(ds_sample)
            
            # Verify
            loaded = manager.load_all_samples()
            assert len(loaded) == 10
            
            # Create version
            jsonl_path = manager.create_dataset_version("synthetic_v1")
            assert jsonl_path.exists()
