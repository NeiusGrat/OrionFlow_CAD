from app.cad.feature_graph import FeatureGraph, Feature

def build_cylinder_graph(params: dict) -> FeatureGraph:
    return FeatureGraph(
        part_type="cylinder",
        features=[
            Feature(
                id="sketch_1",
                type="circle",
                params={
                    "radius": params["radius"]
                }
            ),
            Feature(
                id="extrude_1",
                type="extrude",
                params={
                    "height": params["height"]
                }
            )
        ]
    )
