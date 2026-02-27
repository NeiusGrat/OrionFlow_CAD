"""Tests for DeepCAD -> OFL converter."""

import pytest
from orionflow_ofl.data_pipeline.deepcad_converter import DeepCADConverter


@pytest.fixture
def converter():
    return DeepCADConverter(scale=50.0)


def _make_rect_sketch(x1, y1, x2, y2, plane_nz=1):
    return {
        "type": "sketch",
        "plane": {"x": 0, "y": 0, "z": 0, "nx": 0, "ny": 0, "nz": plane_nz},
        "loops": [{
            "curves": [
                {"type": "line", "start": [x1, y1], "end": [x2, y1]},
                {"type": "line", "start": [x2, y1], "end": [x2, y2]},
                {"type": "line", "start": [x2, y2], "end": [x1, y2]},
                {"type": "line", "start": [x1, y2], "end": [x1, y1]},
            ]
        }],
    }


def _make_circle_sketch(radius, center=(0, 0), plane_nz=1):
    return {
        "type": "sketch",
        "plane": {"x": 0, "y": 0, "z": 0, "nx": 0, "ny": 0, "nz": plane_nz},
        "loops": [{
            "curves": [
                {"type": "circle", "center": list(center), "radius": radius}
            ]
        }],
    }


class TestSimpleRectangle:
    def test_basic_conversion(self, converter):
        deepcad = {
            "sequence": [
                _make_rect_sketch(-0.5, -0.5, 0.5, 0.5),
                {"type": "extrude", "extent_one": 0.2, "boolean": "new"},
            ]
        }
        code = converter.convert(deepcad, model_id="test_rect")
        assert code is not None
        assert "from orionflow_ofl import *" in code
        assert ".rect(" in code
        assert ".extrude(" in code
        assert 'export(part, "test_rect.step")' in code

    def test_scaled_dimensions(self, converter):
        deepcad = {
            "sequence": [
                _make_rect_sketch(-0.5, -0.5, 0.5, 0.5),
                {"type": "extrude", "extent_one": 0.2, "boolean": "new"},
            ]
        }
        code = converter.convert(deepcad, model_id="test_scale")
        assert "width = 50.0" in code
        assert "height = 50.0" in code
        assert "thickness = 10.0" in code


class TestCircleWithHole:
    def test_circle_extrude(self, converter):
        deepcad = {
            "sequence": [
                _make_circle_sketch(0.5),
                {"type": "extrude", "extent_one": 0.3, "boolean": "new"},
            ]
        }
        code = converter.convert(deepcad, model_id="test_circle")
        assert code is not None
        assert ".circle(" in code
        assert ".extrude(" in code

    def test_circle_with_hole(self, converter):
        deepcad = {
            "sequence": [
                _make_circle_sketch(0.5),
                {"type": "extrude", "extent_one": 0.3, "boolean": "new"},
                _make_circle_sketch(0.1),
                {"type": "extrude", "extent_one": 0.3, "boolean": "cut"},
            ]
        }
        code = converter.convert(deepcad, model_id="test_hole")
        assert code is not None
        assert "Hole(" in code
        assert ".through()" in code or ".to_depth(" in code


class TestSkipCases:
    def test_skip_complex_sketch(self, converter):
        """Sketch with arcs should return None."""
        deepcad = {
            "sequence": [
                {
                    "type": "sketch",
                    "plane": {"x": 0, "y": 0, "z": 0, "nx": 0, "ny": 0, "nz": 1},
                    "loops": [{
                        "curves": [
                            {"type": "line", "start": [0, 0], "end": [1, 0]},
                            {"type": "arc", "start": [1, 0], "end": [0, 1], "mid": [0.7, 0.7]},
                            {"type": "line", "start": [0, 1], "end": [0, 0]},
                        ]
                    }],
                },
                {"type": "extrude", "extent_one": 0.2, "boolean": "new"},
            ]
        }
        code = converter.convert(deepcad, model_id="test_arc")
        assert code is None

    def test_skip_non_axis_plane(self, converter):
        """Non-axis-aligned plane should return None."""
        deepcad = {
            "sequence": [
                {
                    "type": "sketch",
                    "plane": {"x": 0, "y": 0, "z": 0, "nx": 0.707, "ny": 0.707, "nz": 0},
                    "loops": [{
                        "curves": [
                            {"type": "line", "start": [-0.5, -0.5], "end": [0.5, -0.5]},
                            {"type": "line", "start": [0.5, -0.5], "end": [0.5, 0.5]},
                            {"type": "line", "start": [0.5, 0.5], "end": [-0.5, 0.5]},
                            {"type": "line", "start": [-0.5, 0.5], "end": [-0.5, -0.5]},
                        ]
                    }],
                },
                {"type": "extrude", "extent_one": 0.2, "boolean": "new"},
            ]
        }
        code = converter.convert(deepcad, model_id="test_plane")
        assert code is None

    def test_additive_join(self, converter):
        """Join operations should generate additive features."""
        deepcad = {
            "sequence": [
                _make_rect_sketch(-0.5, -0.5, 0.5, 0.5),
                {"type": "extrude", "extent_one": 0.2, "boolean": "new"},
                _make_rect_sketch(-0.3, -0.3, 0.3, 0.3),
                {"type": "extrude", "extent_one": 0.1, "boolean": "join"},
            ]
        }
        code = converter.convert(deepcad, model_id="test_join")
        assert code is not None
        assert "part +=" in code
        assert ".rect(30.0, 30.0)" in code
        assert ".extrude(5.0)" in code

    def test_empty_sequence(self, converter):
        code = converter.convert({"sequence": []}, model_id="empty")
        assert code is None


class TestScaleFactor:
    def test_custom_scale(self):
        converter = DeepCADConverter(scale=100.0)
        deepcad = {
            "sequence": [
                _make_rect_sketch(-0.5, -0.5, 0.5, 0.5),
                {"type": "extrude", "extent_one": 0.2, "boolean": "new"},
            ]
        }
        code = converter.convert(deepcad, model_id="scaled")
        assert code is not None
        assert "width = 100.0" in code
        assert "thickness = 20.0" in code
