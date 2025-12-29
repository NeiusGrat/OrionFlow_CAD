from app.cad.feature_graph import FeatureGraph, Feature

def build_cylinder_graph(params: dict) -> FeatureGraph:
    return FeatureGraph(
        part_type="cylinder",
        features=[
            Feature(
                id="sketch_1",
                type="circle",
                params={
                    "radius": params.get("radius", 20)
                }
            ),
            Feature(
                id="extrude_1",
                type="extrude",
                params={
                    "height": params.get("height", 100)
                },
                depends_on=["sketch_1"]
            )
        ]
    )

def build_box_graph(params: dict) -> FeatureGraph:
    return FeatureGraph(
        part_type="box",
        features=[
            Feature(
                id="sketch_1",
                type="rectangle",
                params={
                    "length": params.get("length", 50),
                    "width": params.get("width", 50)
                }
            ),
            Feature(
                id="extrude_1",
                type="extrude",
                params={
                    "height": params.get("height", 5)
                },
                depends_on=["sketch_1"]
            )
        ]
    )

def build_shaft_graph(params: dict) -> FeatureGraph:
    # A shaft might be two cylinders stacked to simulate a step
    # For simplicity, we create one base cylinder and a smaller extension
    radius = params.get("radius", 10)
    height = params.get("height", 100)
    
    return FeatureGraph(
        part_type="shaft",
        features=[
            Feature(
                id="base_sketch",
                type="circle",
                params={
                    "radius": radius
                }
            ),
            Feature(
                id="base_extrude",
                type="extrude",
                params={
                    "height": height * 0.7
                },
                depends_on=["base_sketch"]
            ),
            Feature(
                id="tip_sketch",
                type="circle",
                params={
                    "radius": radius * 0.6
                },
                depends_on=["base_extrude"]
            ),
            Feature(
                id="tip_extrude",
                type="extrude",
                params={
                    "height": height * 0.3
                },
                depends_on=["tip_sketch"]
            )
        ]
    )
