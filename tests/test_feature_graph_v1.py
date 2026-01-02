from app.domain.feature_graph_v1 import FeatureGraphV1
from pydantic import ValidationError
import pytest

def test_minimal_valid_graph():
    graph = FeatureGraphV1(
        schema_version="1.0",
        units="mm",
        metadata={"intent": "test box"},
        parameters={
            "width": {"type": "float", "value": 10},
            "height": {"type": "float", "value": 10}
        },
        sketches=[
            {
                "id": "sketch1",
                "plane": "XY",
                "primitives": [
                    {
                        "id": "rect1",
                        "type": "rectangle",
                        "params": {
                            "width": "width",
                            "height": "height"
                        }
                    }
                ],
                "constraints": []
            }
        ],
        features=[
            {
                "id": "extrude1",
                "type": "extrude",
                "sketch": "sketch1",
                "params": {
                    "depth": 5
                }
            }
        ]
    )

    assert graph.schema_version == "1.0"
    assert graph.parameters["width"].value == 10
    assert graph.sketches[0].primitives[0].type == "rectangle"

def test_invalid_valid_graph():
    """Test that invalid schema raises ValidationError"""
    with pytest.raises(ValidationError):
        FeatureGraphV1(
            schema_version="0.9", # Invalid version
            units="mm",
            metadata={},
            parameters={},
            sketches=[],
            features=[]
        )
