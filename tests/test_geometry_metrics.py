"""
Tests for Geometry Metrics Calculator (Step 6).

Tests the geometry property extraction from Build123d solids.
"""
import pytest
from app.validation.geometry_metrics import (
    calculate_geometry_metrics,
    validate_manufacturing_constraints
)
from app.domain.training_sample import GeometryMetrics


class TestCalculateGeometryMetrics:
    """Test calculate_geometry_metrics function."""
    
    def test_calculate_metrics_none_input(self):
        """Test handling of None input."""
        metrics = calculate_geometry_metrics(None)
        
        assert metrics.volume == 0.0
        assert metrics.is_valid is False
        assert metrics.is_manifold is False
    
    def test_calculate_metrics_string_input(self):
        """Test handling of cloud entity string."""
        metrics = calculate_geometry_metrics("onshape_cloud_entity")
        
        assert metrics.volume == 0.0
        assert metrics.is_valid is False
    
    def test_calculate_metrics_mock_solid(self):
        """Test with mock solid object."""
        class MockSolid:
            volume = 1000.0
            area = 600.0
            is_valid = True
            
            def bounding_box(self):
                class BBox:
                    class Point:
                        def __init__(self, x, y, z):
                            self.X = x
                            self.Y = y
                            self.Z = z
                    min = Point(0, 0, 0)
                    max = Point(10, 10, 10)
                return BBox()
            
            def faces(self):
                return [1, 2, 3, 4, 5, 6]  # 6 faces
            
            def edges(self):
                return list(range(12))  # 12 edges
            
            def vertices(self):
                return list(range(8))  # 8 vertices
        
        metrics = calculate_geometry_metrics(MockSolid())
        
        assert metrics.volume == 1000.0
        assert metrics.surface_area == 600.0
        assert metrics.is_valid is True
        assert metrics.is_manifold is True  # Valid solid with volume
        assert metrics.face_count == 6
        assert metrics.edge_count == 12
        assert metrics.vertex_count == 8
        assert "x_min" in metrics.bounding_box
        assert metrics.bounding_box["x_max"] == 10.0


class TestValidateManufacturingConstraints:
    """Test manufacturing constraint validation."""
    
    def test_valid_geometry(self):
        """Test validation of valid geometry."""
        metrics = GeometryMetrics(
            volume=1000.0,
            surface_area=600.0,
            bounding_box={
                "x_min": 0.0, "x_max": 10.0,
                "y_min": 0.0, "y_max": 10.0,
                "z_min": 0.0, "z_max": 10.0
            },
            is_valid=True,
            is_manifold=True
        )
        
        result = validate_manufacturing_constraints(metrics)
        
        assert result["valid"] is True
        assert len(result["errors"]) == 0
    
    def test_too_small_volume(self):
        """Test detection of too small volume."""
        metrics = GeometryMetrics(
            volume=0.5,  # Below 1.0 minimum
            surface_area=1.0,
            bounding_box={},
            is_valid=True,
            is_manifold=True
        )
        
        result = validate_manufacturing_constraints(metrics, min_volume=1.0)
        
        assert result["valid"] is False
        assert any("volume" in e.lower() for e in result["errors"])
    
    def test_invalid_geometry(self):
        """Test detection of invalid geometry."""
        metrics = GeometryMetrics(
            volume=100.0,
            surface_area=60.0,
            bounding_box={},
            is_valid=False,  # Invalid
            is_manifold=True
        )
        
        result = validate_manufacturing_constraints(metrics)
        
        assert result["valid"] is False
        assert any("validity" in e.lower() for e in result["errors"])
    
    def test_non_manifold_geometry(self):
        """Test detection of non-manifold geometry."""
        metrics = GeometryMetrics(
            volume=100.0,
            surface_area=60.0,
            bounding_box={},
            is_valid=True,
            is_manifold=False  # Not manifold
        )
        
        result = validate_manufacturing_constraints(metrics)
        
        assert result["valid"] is False
        assert any("manifold" in e.lower() for e in result["errors"])
    
    def test_dimension_too_small(self):
        """Test detection of too small dimensions."""
        metrics = GeometryMetrics(
            volume=100.0,
            surface_area=60.0,
            bounding_box={
                "x_min": 0.0, "x_max": 0.1,  # Only 0.1mm wide
                "y_min": 0.0, "y_max": 10.0,
                "z_min": 0.0, "z_max": 10.0
            },
            is_valid=True,
            is_manifold=True
        )
        
        result = validate_manufacturing_constraints(metrics, min_dimension=0.5)
        
        assert result["valid"] is False
        assert any("dimension" in e.lower() and "below" in e.lower() for e in result["errors"])
    
    def test_dimension_too_large(self):
        """Test detection of too large dimensions."""
        metrics = GeometryMetrics(
            volume=100.0,
            surface_area=60.0,
            bounding_box={
                "x_min": 0.0, "x_max": 2000.0,  # 2000mm = 2m
                "y_min": 0.0, "y_max": 10.0,
                "z_min": 0.0, "z_max": 10.0
            },
            is_valid=True,
            is_manifold=True
        )
        
        result = validate_manufacturing_constraints(metrics, max_dimension=1000.0)
        
        assert result["valid"] is False
        assert any("exceeds" in e.lower() for e in result["errors"])
