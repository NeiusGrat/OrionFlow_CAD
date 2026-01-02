from app.cad.onshape.adapter import OnshapeFeatureGraphAdapter
from app.domain.feature_graph_v1 import FeatureGraphV1, SketchGraph, SketchPrimitive, Feature, Parameter

def test_onshape_adapter_instantiates():
    adapter = OnshapeFeatureGraphAdapter(
        "doc", "ws", "el"
    )
    assert adapter is not None
    assert adapter.client is not None
    assert adapter.sketch_adapter is not None

def test_onshape_adapter_compiles_simple_graph():
    # Setup Adapter
    adapter = OnshapeFeatureGraphAdapter("d", "w", "e")
    
    # Create simple FeatureGraph
    graph = FeatureGraphV1(
        schema_version="1.0",
        units="mm",
        metadata={},
        parameters={
            "length": Parameter(type="float", value=100.0),
            "width": Parameter(type="float", value=50.0),
            "depth": Parameter(type="float", value=20.0)
        },
        sketches=[
            SketchGraph(
                id="s1",
                plane="XY",
                primitives=[
                    SketchPrimitive(
                        id="p1", 
                        type="rectangle", 
                        params={"width": "$length", "height": "$width"}
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
                params={"depth": "$depth"},
                targets=[]
            )
        ]
    )
    
    # Run Compile (Mocked Client)
    # This should run without error because client.post is mocked
    adapter.compile(graph)
