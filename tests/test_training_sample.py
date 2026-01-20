"""
Tests for Training Sample Model and Geometry Metrics (Step 6).

Tests the gold dataset structure for LLM fine-tuning preparation.
"""
import pytest
from app.domain.training_sample import TrainingSample, GeometryMetrics


class TestGeometryMetrics:
    """Test GeometryMetrics model."""
    
    def test_create_geometry_metrics(self):
        """Test creating GeometryMetrics with all fields."""
        metrics = GeometryMetrics(
            volume=1000.0,
            surface_area=600.0,
            bounding_box={
                "x_min": 0.0, "x_max": 10.0,
                "y_min": 0.0, "y_max": 10.0,
                "z_min": 0.0, "z_max": 10.0
            },
            is_valid=True,
            is_manifold=True,
            face_count=6,
            edge_count=12,
            vertex_count=8
        )
        
        assert metrics.volume == 1000.0
        assert metrics.surface_area == 600.0
        assert metrics.is_valid is True
        assert metrics.is_manifold is True
        assert metrics.face_count == 6
    
    def test_empty_geometry_metrics(self):
        """Test creating empty metrics for failures."""
        metrics = GeometryMetrics.empty()
        
        assert metrics.volume == 0.0
        assert metrics.is_valid is False
        assert metrics.is_manifold is False
    
    def test_geometry_metrics_serialization(self):
        """Test JSON serialization round-trip."""
        metrics = GeometryMetrics(
            volume=500.0,
            surface_area=300.0,
            bounding_box={"x_min": 0.0, "x_max": 5.0},
            is_valid=True,
            is_manifold=True
        )
        
        data = metrics.model_dump()
        restored = GeometryMetrics(**data)
        
        assert restored.volume == 500.0
        assert restored.bounding_box["x_max"] == 5.0


class TestTrainingSample:
    """Test TrainingSample model."""
    
    def test_create_training_sample_success(self):
        """Test creating a successful training sample."""
        sample = TrainingSample(
            prompt="Create a 30x20x10 box",
            construction_plan={"steps": ["create sketch", "extrude"]},
            feature_graph={"version": "1.0", "sketches": [], "features": []},
            compile_success=True,
            geometry_metrics=GeometryMetrics(
                volume=6000.0,
                surface_area=2200.0,
                bounding_box={},
                is_valid=True,
                is_manifold=True
            ),
            llm_model="llama-3.3-70b-versatile"
        )
        
        assert sample.prompt == "Create a 30x20x10 box"
        assert sample.compile_success is True
        assert sample.geometry_metrics.volume == 6000.0
        assert sample.sample_id != ""  # UUID generated
        assert sample.timestamp != ""  # ISO timestamp generated
    
    def test_create_training_sample_failure(self):
        """Test creating a failed training sample."""
        sample = TrainingSample(
            prompt="Create something invalid",
            construction_plan={},
            feature_graph={},
            compile_success=False,
            compile_error="Invalid geometry: zero volume",
            geometry_metrics=None
        )
        
        assert sample.compile_success is False
        assert sample.compile_error == "Invalid geometry: zero volume"
        assert sample.geometry_metrics is None
    
    def test_sample_quality_score_success(self):
        """Test quality score calculation for successful sample."""
        sample = TrainingSample(
            prompt="Test",
            construction_plan={},
            feature_graph={"version": "1.0"},
            compile_success=True,
            geometry_metrics=GeometryMetrics(
                volume=100.0,
                surface_area=60.0,
                bounding_box={},
                is_valid=True,
                is_manifold=True
            ),
            json_parse_success=True,
            json_repair_applied=False
        )
        
        score = sample.calculate_quality_score()
        
        # 0.5 (success) + 0.2 (valid) + 0.1 (manifold) + 0.1 (volume>0) + 0.1 (clean json)
        assert score == pytest.approx(1.0)
    
    def test_sample_quality_score_failure(self):
        """Test quality score calculation for failed sample."""
        sample = TrainingSample(
            prompt="Test",
            construction_plan={},
            feature_graph={},
            compile_success=False,
            geometry_metrics=None
        )
        
        score = sample.calculate_quality_score()
        
        # No points for failure
        assert score < 0.2
    
    def test_to_training_dict(self):
        """Test conversion to training format."""
        sample = TrainingSample(
            prompt="Create a cylinder",
            construction_plan={"steps": ["circle", "extrude"]},
            feature_graph={"version": "1.0", "features": [{"type": "extrude"}]},
            compile_success=True
        )
        
        training_dict = sample.to_training_dict()
        
        assert "prompt" in training_dict
        assert "completion" in training_dict
        assert "metadata" in training_dict
        assert training_dict["prompt"] == "Create a cylinder"
        assert training_dict["metadata"]["compile_success"] is True
    
    def test_sample_serialization(self):
        """Test full JSON serialization round-trip."""
        sample = TrainingSample(
            prompt="Test prompt",
            construction_plan={"param": "value"},
            feature_graph={"version": "1.0"},
            compile_success=True,
            execution_trace={"events": []},
            retry_count=1,
            llm_model="test-model",
            llm_raw_response='{"version": "1.0"}',
            json_parse_success=True,
            json_repair_applied=False,
            backend="build123d"
        )
        
        # Serialize to JSON
        json_str = sample.model_dump_json()
        
        # Deserialize back
        restored = TrainingSample.model_validate_json(json_str)
        
        assert restored.prompt == sample.prompt
        assert restored.compile_success == sample.compile_success
        assert restored.llm_model == sample.llm_model
    
    def test_json_validation_tracking(self):
        """Test JSON validation error tracking."""
        sample = TrainingSample(
            prompt="Test",
            construction_plan={},
            feature_graph={},
            compile_success=True,
            json_parse_success=True,
            json_repair_applied=True,
            json_validation_errors=["Missing 'version' field", "Auto-repaired"]
        )
        
        assert sample.json_repair_applied is True
        assert len(sample.json_validation_errors) == 2
        
        # Quality score should be lower due to repair
        score = sample.calculate_quality_score()
        assert score < 1.0  # Not perfect due to repair
