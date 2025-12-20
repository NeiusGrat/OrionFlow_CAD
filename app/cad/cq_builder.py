import cadquery as cq
from app.cad.feature_graph import FeatureGraph

def build_from_graph(graph: FeatureGraph):
    wp = cq.Workplane(graph.base_plane)

    for feature in graph.features:
        if feature.type == "circle":
            wp = wp.circle(feature.params["radius"])

        elif feature.type == "extrude":
            wp = wp.extrude(feature.params["height"])

        else:
            raise ValueError(f"Unsupported feature: {feature.type}")

    return wp
