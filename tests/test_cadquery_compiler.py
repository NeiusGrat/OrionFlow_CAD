"""
Tests for CadQuery Compiler.

Validates compilation pipeline from FeatureGraphV1 to geometry files.
"""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.compilers.cadquery_compiler import CadQueryCompiler
from app.domain.feature_graph_v1 import (
    FeatureGraphV1,
    SketchGraph,
    SketchPrimitive,
    SketchConstraint,
    Feature,
    Parameter
)
from app.domain.execution_trace import ExecutionTrace


class TestCadQueryCompiler:
    """Test suite for CadQueryCompiler."""
    
    @pytest.fixture
    def output_dir(self):
        """Create temporary output directory."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def compiler(self, output_dir):
        """Create compiler instance."""
        return CadQueryCompiler(output_dir=output_dir)
    
    @pytest.fixture
    def simple_box_graph(self) -> FeatureGraphV1:
        """Create a simple box 100x50x20mm."""
        return FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={"intent": "Box 100x50x20mm"},
            parameters={
                "length": Parameter(type="float", value=100.0),
                "width": Parameter(type="float", value=50.0),
                "height": Parameter(type="float", value=20.0)
            },
            sketches=[
                SketchGraph(
                    id="sketch_1",
                    plane="XY",
                    primitives=[
                        SketchPrimitive(
                            id="rect_1",
                            type="rectangle",
                            params={"width": "$length", "height": "$width"},
                            construction=False
                        )
                    ],
                    constraints=[]
                )
            ],
            features=[
                Feature(
                    id="extrude_1",
                    type="extrude",
                    sketch="sketch_1",
                    params={"depth": "$height"}
                )
            ]
        )
    
    @pytest.fixture
    def simple_cylinder_graph(self) -> FeatureGraphV1:
        """Create a simple cylinder r=10, h=20."""
        return FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={"intent": "Cylinder r10 h20"},
            parameters={
                "radius": Parameter(type="float", value=10.0),
                "height": Parameter(type="float", value=20.0)
            },
            sketches=[
                SketchGraph(
                    id="sketch_1",
                    plane="XY",
                    primitives=[
                        SketchPrimitive(
                            id="circle_1",
                            type="circle",
                            params={"radius": "$radius"},
                            construction=False
                        )
                    ],
                    constraints=[]
                )
            ],
            features=[
                Feature(
                    id="extrude_1",
                    type="extrude",
                    sketch="sketch_1",
                    params={"depth": "$height"}
                )
            ]
        )
    
    def test_compile_simple_box(self, compiler, simple_box_graph):
        """Test compiling a simple box produces valid geometry files."""
        step_path, stl_path, glb_path, trace = compiler.compile(
            simple_box_graph, "test_box"
        )
        
        # Check trace succeeded
        assert trace.success is True
        assert len(trace.events) >= 2  # At least sketch + feature + export
        
        # Check files exist
        assert step_path.exists(), f"STEP file not found: {step_path}"
        assert stl_path.exists(), f"STL file not found: {stl_path}"
        assert glb_path.exists(), f"GLB file not found: {glb_path}"
        
        # Check files have content
        assert step_path.stat().st_size > 0, "STEP file is empty"
        assert stl_path.stat().st_size > 0, "STL file is empty"
        assert glb_path.stat().st_size > 0, "GLB file is empty"
    
    def test_compile_cylinder(self, compiler, simple_cylinder_graph):
        """Test compiling a cylinder produces valid geometry files."""
        step_path, stl_path, glb_path, trace = compiler.compile(
            simple_cylinder_graph, "test_cylinder"
        )
        
        assert trace.success is True
        assert step_path.exists()
        assert stl_path.exists()
        assert glb_path.exists()
    
    def test_parameter_resolution(self, compiler, simple_box_graph):
        """Test that $param references are resolved correctly."""
        # The box uses $length, $width, $height - if these resolve correctly,
        # the geometry will be created successfully
        step_path, stl_path, glb_path, trace = compiler.compile(
            simple_box_graph, "test_params"
        )
        
        assert trace.success is True
        
        # All events should be successful
        for event in trace.events:
            assert event.status == "success", f"Event {event.stage} failed: {event.message}"
    
    def test_trace_contains_sketch_events(self, compiler, simple_box_graph):
        """Test that execution trace includes sketch compilation events."""
        _, _, _, trace = compiler.compile(simple_box_graph, "test_trace")
        
        sketch_events = [e for e in trace.events if "sketch" in e.stage]
        assert len(sketch_events) >= 1, "No sketch events in trace"
    
    def test_trace_contains_feature_events(self, compiler, simple_box_graph):
        """Test that execution trace includes feature events."""
        _, _, _, trace = compiler.compile(simple_box_graph, "test_features")
        
        feature_events = [e for e in trace.events if "feature" in e.stage]
        assert len(feature_events) >= 1, "No feature events in trace"
    
    def test_step_file_valid_format(self, compiler, simple_box_graph):
        """Test that STEP file contains valid STEP header."""
        step_path, _, _, _ = compiler.compile(simple_box_graph, "test_step_format")
        
        content = step_path.read_text()
        
        # STEP files start with ISO-10303-21 header
        assert "ISO-10303-21" in content or "STEP" in content.upper(), \
            "STEP file missing standard header"
    
    def test_stl_file_valid_format(self, compiler, simple_box_graph):
        """Test that STL file contains valid STL structure."""
        _, stl_path, _, _ = compiler.compile(simple_box_graph, "test_stl_format")
        
        content = stl_path.read_bytes()
        
        # Binary STL starts with 80-byte header, or ASCII starts with "solid"
        is_ascii = content[:5].lower() == b"solid"
        is_binary = len(content) > 80  # Has header
        
        assert is_ascii or is_binary, "STL file format not recognized"
    
    def test_glb_file_loadable(self, compiler, simple_box_graph):
        """Test that GLB file can be loaded by trimesh."""
        import trimesh
        
        _, _, glb_path, _ = compiler.compile(simple_box_graph, "test_glb_load")
        
        # Should load without error
        mesh = trimesh.load(str(glb_path))
        
        # Should have vertices and faces
        assert mesh.vertices.shape[0] > 0, "GLB has no vertices"
        assert mesh.faces.shape[0] > 0, "GLB has no faces"
    
    def test_missing_sketch_reference_fails(self, compiler):
        """Test that referencing non-existent sketch fails gracefully."""
        bad_graph = FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={"intent": "Bad reference"},
            parameters={
                "height": Parameter(type="float", value=10.0)
            },
            sketches=[],  # No sketches defined
            features=[
                Feature(
                    id="extrude_1",
                    type="extrude",
                    sketch="nonexistent_sketch",  # This doesn't exist
                    params={"depth": 10.0}
                )
            ]
        )
        
        with pytest.raises(Exception):  # Should raise FeatureCompilationError
            compiler.compile(bad_graph, "test_bad_ref")
    
    def test_missing_parameter_reference_fails(self, compiler):
        """Test that referencing undefined parameter fails."""
        bad_graph = FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={"intent": "Bad param"},
            parameters={},  # No parameters defined
            sketches=[
                SketchGraph(
                    id="sketch_1",
                    plane="XY",
                    primitives=[
                        SketchPrimitive(
                            id="rect_1",
                            type="rectangle",
                            params={"width": "$undefined", "height": 10.0},  # $undefined doesn't exist
                            construction=False
                        )
                    ],
                    constraints=[]
                )
            ],
            features=[
                Feature(
                    id="extrude_1",
                    type="extrude",
                    sketch="sketch_1",
                    params={"depth": 10.0}
                )
            ]
        )
        
        with pytest.raises(Exception):  # Should raise SketchCompilationError
            compiler.compile(bad_graph, "test_bad_param")


class TestParameterResolution:
    """Test parameter resolution edge cases."""
    
    @pytest.fixture
    def compiler(self):
        with TemporaryDirectory() as tmpdir:
            yield CadQueryCompiler(output_dir=Path(tmpdir))
    
    def test_literal_float_value(self, compiler):
        """Test that literal float values work."""
        graph = FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={"intent": "Literal values"},
            parameters={},
            sketches=[
                SketchGraph(
                    id="s1",
                    plane="XY",
                    primitives=[
                        SketchPrimitive(
                            id="r1",
                            type="rectangle",
                            params={"width": 50.0, "height": 30.0},  # Literal floats
                            construction=False
                        )
                    ],
                    constraints=[]
                )
            ],
            features=[
                Feature(
                    id="f1",
                    type="extrude",
                    sketch="s1",
                    params={"depth": 10.0}  # Literal float
                )
            ]
        )
        
        _, _, _, trace = compiler.compile(graph, "test_literal")
        assert trace.success is True
    
    def test_string_float_value(self, compiler):
        """Test that string-encoded floats work."""
        graph = FeatureGraphV1(
            schema_version="1.0",
            units="mm",
            metadata={"intent": "String floats"},
            parameters={},
            sketches=[
                SketchGraph(
                    id="s1",
                    plane="XY",
                    primitives=[
                        SketchPrimitive(
                            id="r1",
                            type="rectangle",
                            params={"width": "50.0", "height": "30.0"},  # String floats
                            construction=False
                        )
                    ],
                    constraints=[]
                )
            ],
            features=[
                Feature(
                    id="f1",
                    type="extrude",
                    sketch="s1",
                    params={"depth": "10.0"}  # String float
                )
            ]
        )
        
        _, _, _, trace = compiler.compile(graph, "test_string_float")
        assert trace.success is True
