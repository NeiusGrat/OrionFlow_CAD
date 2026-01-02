from app.domain.feature_graph_v1 import FeatureGraphV1
from .client import OnshapeClient
from .sketch import OnshapeSketchAdapter
from .features import OnshapeFeatureAdapter


class OnshapeFeatureGraphAdapter:
    def __init__(self, document_id, workspace_id, element_id):
        self.client = OnshapeClient()
        self.sketch_adapter = OnshapeSketchAdapter(
            self.client, document_id, workspace_id, element_id
        )
        self.feature_adapter = OnshapeFeatureAdapter(
            self.client, document_id, workspace_id, element_id
        )

    def compile(self, graph: FeatureGraphV1):
        for sketch in graph.sketches:
            self.sketch_adapter.create_sketch(sketch.id)

            for prim in sketch.primitives:
                if prim.type == "rectangle":
                    w = prim.params["width"]
                    h = prim.params["height"]
                    if isinstance(w, str): w = graph.parameters[w.lstrip("$")].value
                    if isinstance(h, str): h = graph.parameters[h.lstrip("$")].value
                    
                    self.sketch_adapter.add_rectangle(w, h)
                elif prim.type == "circle":
                    r = prim.params["radius"]
                    if isinstance(r, str): r = graph.parameters[r.lstrip("$")].value
                    self.sketch_adapter.add_circle(r)

        for feature in graph.features:
            if feature.type == "extrude":
                depth = feature.params["depth"]
                if isinstance(depth, str):
                    # Strip $ if present, though resolve_param logic usually handles this?
                    # The graph.parameters key is the raw name "width" not "$width".
                    # But the param value in sketch might be "$width".
                    # Let's assume strict V1 for now: params keys match exactly what's in graph.parameters if they are references.
                    # Wait, prim.params["width"] might be "$width".
                    # In V1 compiler we had helper for this. Here we do it inline for simplicity per instructions.
                    clean_key = depth.lstrip("$")
                    depth = graph.parameters[clean_key].value
                self.feature_adapter.extrude(depth)
