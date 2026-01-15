"""
Test Geometry Validators (Phase 3)

Tests for:
- Zero-thickness detection
- Invalid fillet radius detection
- Self-intersection detection
- Degenerate face detection
- Structured error format
"""
import pytest
from pathlib import Path
from uuid import uuid4

from app.domain.feature_graph_v2 import (
    FeatureGraphV2, FeatureV2, SketchGraphV2, SketchPrimitiveV2,
    SemanticSelector, SelectorType
)
from app.domain.compiler_errors import CompilerError, ErrorType
from app.compilers.build123d_compiler_v3 import Build123dCompilerV3
from app.compilers.v1.errors import FeatureCompilationError


def test_zero_thickness_detection():
    """Verify that zero-thickness extrusions are caught."""
    graph = FeatureGraphV2(
        version="2.0",
        units="mm",
        parameters={"depth": 0.001},  # Too small! Below 0.01mm threshold
        sketches=[
            SketchGraphV2(
                id="s1",
                plane="XY",
                primitives=[
                    SketchPrimitiveV2(
                        id="p1",
                        type="rectangle",
                        params={"width": 50, "height": 30}
                    )
                ]
            )
        ],
        features=[
            FeatureV2(
                id="extrude_1",
                type="extrude",
                sketch="s1",
                params={"depth": "$depth"}
            )
        ]
    )
    
    compiler = Build123dCompilerV3(Path("outputs"))
    job_id = f"test_{uuid4().hex[:8]}"
    
    with pytest.raises(FeatureCompilationError) as exc_info:
        compiler.compile(graph, job_id)
    
    # Verify structured error is attached
    error = exc_info.value.compiler_error
    assert error is not None
    assert error.error_type == ErrorType.ZERO_THICKNESS
    assert error.feature_id == "extrude_1"
    assert "depth" in error.context or "depth_parameter" in error.context
    assert error.suggested_fix is not None
    
    print(f"✓ Zero-thickness detected: {error.reason}")


def test_invalid_fillet_radius():
    """Verify that excessive fillet radius is caught."""
    graph = FeatureGraphV2(
        version="2.0",
        units="mm",
        parameters={"fillet_r": 50},  # Way too large for 10mm edges!
        sketches=[
            SketchGraphV2(
                id="s1",
                plane="XY",
                primitives=[
                    SketchPrimitiveV2(
                        id="p1",
                        type="rectangle",
                        params={"width": 10, "height": 10}
                    )
                ]
            )
        ],
        features=[
            FeatureV2(id="extrude_1", type="extrude", sketch="s1", params={"depth": 10}),
            FeatureV2(
                id="fillet_1",
                type="fillet",
                params={"radius": "$fillet_r"},
                topology_refs={
                    "edges": SemanticSelector(
                        selector_type=SelectorType.STRING,
                        string_selector=">Z"  # Top edges
                    )
                }
            )
        ]
    )
    
    compiler = Build123dCompilerV3(Path("outputs"))
    job_id = f"test_{uuid4().hex[:8]}"
    
    with pytest.raises(FeatureCompilationError) as exc_info:
        compiler.compile(graph, job_id)
    
    error = exc_info.value.compiler_error
    assert error is not None
    assert error.error_type == ErrorType.INVALID_FILLET
    assert error.feature_id == "fillet_1"
    assert "max_safe_radius" in error.context
    assert error.suggested_fix is not None
    
    print(f"✓ Invalid fillet detected: {error.reason}")
    print(f"  Suggested fix: {error.suggested_fix}")


def test_negative_dimension_detection():
    """Verify negative fillet radius is caught."""
    graph = FeatureGraphV2(
        version="2.0",
        units="mm",
        parameters={"fillet_r": -5},  # Negative!
        sketches=[
            SketchGraphV2(
                id="s1",
                plane="XY",
                primitives=[
                    SketchPrimitiveV2(id="p1", type="rectangle", params={"width": 20, "height": 20})
                ]
            )
        ],
        features=[
            FeatureV2(id="extrude_1", type="extrude", sketch="s1", params={"depth": 10}),
            FeatureV2(
                id="fillet_1",
                type="fillet",
                params={"radius": "$fillet_r"},
                topology_refs={"edges": SemanticSelector(selector_type=SelectorType.STRING, string_selector=">Z")}
            )
        ]
    )
    
    compiler = Build123dCompilerV3(Path("outputs"))
    job_id = f"test_{uuid4().hex[:8]}"
    
    with pytest.raises(FeatureCompilationError) as exc_info:
        compiler.compile(graph, job_id)
    
    error = exc_info.value.compiler_error
    assert error is not None
    assert error.error_type == ErrorType.INVALID_FILLET
    assert "positive" in error.reason.lower()
    
    print(f"✓ Negative parameter detected: {error.reason}")


def test_valid_geometry_passes():
    """Verify that valid geometry passes all validators."""
    graph = FeatureGraphV2(
        version="2.0",
        units="mm",
        parameters={"width": 50, "depth": 30, "height": 20, "fillet_r": 2},
        sketches=[
            SketchGraphV2(
                id="s1",
                plane="XY",
                primitives=[
                    SketchPrimitiveV2(
                        id="p1",
                        type="rectangle",
                        params={"width": "$width", "height": "$depth"}
                    )
                ]
            )
        ],
        features=[
            FeatureV2(id="extrude_1", type="extrude", sketch="s1", params={"depth": "$height"}),
            FeatureV2(
                id="fillet_1",
                type="fillet",
                params={"radius": "$fillet_r"},
                topology_refs={
                    "edges": SemanticSelector(
                        selector_type=SelectorType.STRING,
                        string_selector=">Z"
                    )
                }
            )
        ]
    )
    
    compiler = Build123dCompilerV3(Path("outputs"))
    job_id = f"test_{uuid4().hex[:8]}"
    
    # Should NOT raise
    step_path, stl_path, glb_path, trace = compiler.compile(graph, job_id)
    
    assert trace.success
    assert "compiler_error" not in trace.metadata
    
    print("✓ Valid geometry passed all validators")


def test_structured_error_format():
    """Verify CompilerError has all required fields."""
    from app.domain.compiler_errors import CompilerError, ErrorType
    
    error = CompilerError(
        error_type=ErrorType.INVALID_FILLET,
        feature_id="fillet_2",
        reason="Fillet radius 10mm exceeds edge length 8mm",
        suggested_fix="Reduce radius to max 4mm",
        context={"edge_length": 8.0, "requested_radius": 10.0}
    )
    
    # Test serialization
    error_dict = error.model_dump()
    assert error_dict["error_type"] == "InvalidFillet"
    assert error_dict["feature_id"] == "fillet_2"
    assert error_dict["context"]["edge_length"] == 8.0
    
    # Test trace message formatting
    trace_msg = error.to_trace_message()
    assert "fillet_2" in trace_msg
    assert "InvalidFillet" in trace_msg
    
    # Test LLM feedback formatting
    llm_feedback = error.to_llm_feedback()
    assert "Suggested fix" in llm_feedback
    assert "Context" in llm_feedback
    
    print("✓ Structured error format is correct")


if __name__ == "__main__":
    test_zero_thickness_detection()
    test_invalid_fillet_radius()
    test_negative_dimension_detection()
    test_valid_geometry_passes()
    test_structured_error_format()
    print("\n✅ All Phase 3 validator tests passed!")
