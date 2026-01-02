from app.domain.feature_graph_v1 import FeatureGraphV1
from app.compilers.v1.compiler import FeatureGraphCompilerV1
from build123d import Part

def test_basic_extrude():
    graph = FeatureGraphV1(
        schema_version="1.0",
        units="mm",
        metadata={"intent": "box"},
        parameters={
            "w": {"type": "float", "value": 10},
            "h": {"type": "float", "value": 10},
            "d": {"type": "float", "value": 5}
        },
        sketches=[
            {
                "id": "s1",
                "plane": "XY",
                "primitives": [
                    {
                        "id": "r1",
                        "type": "rectangle",
                        "params": {"width": "w", "height": "h"}
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
                "params": {"depth": "d"},
                "targets": []
            }
        ]
    )

    compiler = FeatureGraphCompilerV1()
    solid, trace = compiler.compile(graph)

    assert solid is not None
    assert trace.success is True
    # Check if we got a valid Part/Solid
    assert hasattr(solid, "volume")
    assert solid.volume > 0
