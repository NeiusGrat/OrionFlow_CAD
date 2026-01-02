from app.domain.feature_graph_v1 import FeatureGraphV1
from app.compilers.v1.compiler import FeatureGraphCompilerV1

def test_trace_on_success():
    """Verify trace is emitted on successful compilation."""
    graph = FeatureGraphV1(
        schema_version="1.0",
        units="mm",
        metadata={"intent": "box"},
        parameters={
            "w": {"type": "float", "value": 10}
        },
        sketches=[
            {
                "id": "s1",
                "plane": "XY",
                "primitives": [
                    {
                        "id": "r1",
                        "type": "rectangle",
                        "params": {"width": "w", "height": "w"}
                    }
                ],
                "constraints": []
            }
        ],
        features=[
            {
                "id": "f1",
                "type": "extrude",
                "sketch": "s1",
                "params": {"depth": 5}
            }
        ]
    )

    solid, trace = FeatureGraphCompilerV1().compile(graph)

    assert solid is not None
    assert trace.success is True
    assert len(trace.events) >= 2  # At least sketch_compile and feature_compile
    assert all(event.status == "success" for event in trace.events)


def test_trace_on_failure():
    """Verify trace captures failures."""
    graph = FeatureGraphV1(
        schema_version="1.0",
        units="mm",
        metadata={"intent": "bad graph"},
        parameters={},
        sketches=[],
        features=[]
    )

    solid, trace = FeatureGraphCompilerV1().compile(graph)

    assert solid is None
    assert trace.success is False
    assert len(trace.events) > 0
    # Should have at least one failure event
    assert any(event.status == "failure" for event in trace.events)
