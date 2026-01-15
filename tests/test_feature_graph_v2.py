"""
Tests for FeatureGraph V2 Schema and Compiler.

Tests semantic selector resolution and V2 compilation.
"""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.feature_graph_v2 import (
    FeatureGraphV2, FeatureV2, SketchGraphV2, SketchPrimitiveV2,
    SemanticSelector, SelectorType, GeometricFilter, GeometricFilterType,
    string_selector, semantic_selector, parallel_to_axis, on_face, length_range
)


class TestFeatureGraphV2Schema:
    """Test V2 schema validation."""
    
    def test_basic_v2_schema(self):
        """Test basic V2 schema creation."""
        graph = FeatureGraphV2(
            version="2.0",
            units="mm",
            metadata={"intent": "Test box"},
            parameters={"width": {"type": "float", "value": 30}},
            sketches=[
                SketchGraphV2(
                    id="s1",
                    plane="XY",
                    primitives=[
                        SketchPrimitiveV2(
                            id="p1",
                            type="rectangle",
                            params={"width": 30, "height": 20}
                        )
                    ]
                )
            ],
            features=[
                FeatureV2(
                    id="f1",
                    type="extrude",
                    sketch="s1",
                    params={"depth": 15}
                )
            ]
        )
        
        assert graph.version == "2.0"
        assert len(graph.sketches) == 1
        assert len(graph.features) == 1
    
    def test_feature_with_string_selector(self):
        """Test feature with simple string selector."""
        feature = FeatureV2(
            id="fillet_1",
            type="fillet",
            params={"radius": 2},
            topology_refs={
                "edges": SemanticSelector(
                    selector_type=SelectorType.STRING,
                    string_selector=">Z",
                    description="top edges"
                )
            }
        )
        
        assert feature.topology_refs["edges"].selector_type == SelectorType.STRING
        assert feature.topology_refs["edges"].string_selector == ">Z"
    
    def test_feature_with_semantic_selector(self):
        """Test feature with semantic filter chain."""
        feature = FeatureV2(
            id="fillet_1",
            type="fillet",
            params={"radius": 2},
            topology_refs={
                "edges": SemanticSelector(
                    selector_type=SelectorType.SEMANTIC,
                    filters=[
                        GeometricFilter(
                            type=GeometricFilterType.PARALLEL_TO_AXIS,
                            parameters={"axis": "X"}
                        ),
                        GeometricFilter(
                            type=GeometricFilterType.ON_FACE,
                            parameters={"face_selector": ">Z"}
                        )
                    ],
                    description="top edges parallel to X"
                )
            }
        )
        
        assert feature.topology_refs["edges"].selector_type == SelectorType.SEMANTIC
        assert len(feature.topology_refs["edges"].filters) == 2
    
    def test_helper_functions(self):
        """Test selector helper functions."""
        # String selector helper
        sel1 = string_selector(">Z", "top edges")
        assert sel1.selector_type == SelectorType.STRING
        assert sel1.string_selector == ">Z"
        
        # Semantic selector helper
        sel2 = semantic_selector(
            parallel_to_axis("X"),
            on_face(">Z"),
            description="complex selection"
        )
        assert sel2.selector_type == SelectorType.SEMANTIC
        assert len(sel2.filters) == 2
        
        # Filter helpers
        f1 = parallel_to_axis("Y")
        assert f1.type == GeometricFilterType.PARALLEL_TO_AXIS
        assert f1.parameters["axis"] == "Y"
        
        f2 = length_range(min_length=5, max_length=10)
        assert f2.type == GeometricFilterType.LENGTH_RANGE
        assert f2.parameters["min"] == 5
        assert f2.parameters["max"] == 10


class TestSemanticSelectorMethods:
    """Test SemanticSelector methods."""
    
    def test_is_simple_string(self):
        """Test is_simple_string detection."""
        simple = SemanticSelector(
            selector_type=SelectorType.STRING,
            string_selector=">Z"
        )
        assert simple.is_simple_string() is True
        
        complex_sel = SemanticSelector(
            selector_type=SelectorType.SEMANTIC,
            filters=[parallel_to_axis("X")]
        )
        assert complex_sel.is_simple_string() is False


class TestV2SchemaFromDict:
    """Test creating V2 schema from dict (LLM output simulation)."""
    
    def test_v2_from_dict(self):
        """Test parsing V2 from dict representation."""
        v2_dict = {
            "version": "2.0",
            "units": "mm",
            "metadata": {"intent": "Box with fillet"},
            "parameters": {
                "width": {"type": "float", "value": 30},
                "height": {"type": "float", "value": 15}
            },
            "sketches": [
                {
                    "id": "s1",
                    "plane": "XY",
                    "primitives": [
                        {"id": "p1", "type": "rectangle", "params": {"width": 30, "height": 20}}
                    ],
                    "constraints": []
                }
            ],
            "features": [
                {
                    "id": "f1",
                    "type": "extrude",
                    "sketch": "s1",
                    "params": {"depth": 15}
                },
                {
                    "id": "f2",
                    "type": "fillet",
                    "params": {"radius": 2},
                    "topology_refs": {
                        "edges": {
                            "selector_type": "semantic",
                            "filters": [
                                {"type": "parallel_to_axis", "parameters": {"axis": "X"}}
                            ],
                            "description": "X-parallel edges"
                        }
                    },
                    "dependencies": ["f1"]
                }
            ]
        }
        
        graph = FeatureGraphV2(**v2_dict)
        
        assert graph.version == "2.0"
        assert len(graph.features) == 2
        
        fillet_feature = graph.features[1]
        assert fillet_feature.type == "fillet"
        assert "edges" in fillet_feature.topology_refs


class TestV2CompilerIntegration:
    """Integration tests for V2 compiler (requires Build123d)."""
    
    @pytest.fixture
    def output_dir(self):
        """Create temp output directory."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def simple_box_v2(self) -> FeatureGraphV2:
        """Simple box without selectors (V2 format)."""
        return FeatureGraphV2(
            version="2.0",
            units="mm",
            metadata={"intent": "Simple box"},
            parameters={"depth": {"type": "float", "value": 15}},
            sketches=[
                SketchGraphV2(
                    id="s1",
                    plane="XY",
                    primitives=[
                        SketchPrimitiveV2(
                            id="p1",
                            type="rectangle",
                            params={"width": 30, "height": 20}
                        )
                    ]
                )
            ],
            features=[
                FeatureV2(
                    id="f1",
                    type="extrude",
                    sketch="s1",
                    params={"depth": "$depth"}
                )
            ]
        )
    
    def test_compile_simple_box_v2(self, output_dir, simple_box_v2):
        """Test compiling simple box with V2 compiler."""
        from app.compilers.build123d_compiler_v2 import Build123dCompilerV2
        
        compiler = Build123dCompilerV2(output_dir=output_dir)
        step_path, stl_path, glb_path, trace = compiler.compile(
            simple_box_v2, "test_box_v2"
        )
        
        assert trace.success is True
        assert step_path.exists()
        assert stl_path.exists()
        assert glb_path.exists()
    
    def test_compile_box_with_fillet_string_selector(self, output_dir):
        """Test box with fillet using string selector."""
        from app.compilers.build123d_compiler_v2 import Build123dCompilerV2
        
        graph = FeatureGraphV2(
            version="2.0",
            units="mm",
            metadata={"intent": "Box with fillet"},
            parameters={},
            sketches=[
                SketchGraphV2(
                    id="s1",
                    plane="XY",
                    primitives=[
                        SketchPrimitiveV2(
                            id="p1",
                            type="rectangle",
                            params={"width": 30, "height": 20}
                        )
                    ]
                )
            ],
            features=[
                FeatureV2(
                    id="f1",
                    type="extrude",
                    sketch="s1",
                    params={"depth": 15}
                ),
                FeatureV2(
                    id="f2",
                    type="fillet",
                    params={"radius": 2},
                    topology_refs={
                        "edges": SemanticSelector(
                            selector_type=SelectorType.STRING,
                            string_selector=">Z",
                            description="top edges"
                        )
                    },
                    dependencies=["f1"]
                )
            ]
        )
        
        compiler = Build123dCompilerV2(output_dir=output_dir)
        step_path, stl_path, glb_path, trace = compiler.compile(graph, "test_fillet")
        
        assert trace.success is True
        assert step_path.exists()
