from build123d import *
from app.domain.feature_graph_v1 import FeatureGraphV1
from .errors import FeatureCompilationError


class FeatureCompiler:
    def compile(self, graph: FeatureGraphV1, sketches: dict):
        solid = None

        for feature in graph.features:
            if feature.type == "extrude":
                # If we already have a solid, we might be cutting or joining.
                # But for the minimal Extrude spec, we usually start with one.
                # If solid exists, we should probably operate on it.
                # The provided snippet returns `solid`.
                # Let's implementation basic logic:
                new_solid = self._extrude(feature, sketches, graph)
                
                if solid is None:
                    solid = new_solid
                else:
                    # Default to adding/fusing if multiple features?
                    # Or is this intended to be a sequential modification?
                    # build123d algebra: solid + new_solid
                    solid = solid + new_solid
                    
            else:
                raise FeatureCompilationError(
                    f"Unsupported feature type: {feature.type}"
                )

        return solid

    def _resolve_param(self, value, graph: FeatureGraphV1):
        if isinstance(value, str):
            clean_val = value.lstrip("$")
            if clean_val in graph.parameters:
                return graph.parameters[clean_val].value
            try:
                return float(value)
            except ValueError:
                pass
        return value

    def _extrude(self, feature, sketches, graph):
        try:
            sketch = sketches[feature.sketch]
            
            # Resolve depth
            depth_raw = feature.params["depth"]
            depth = self._resolve_param(depth_raw, graph)

            # extrude() in build123d acts on the current context or takes an object
            # sketch is a Builder object (BuildSketch) or a Sketch object?
            # SketchCompiler returns `bs` which is a Builder.
            # We need the direct sketch object.
            
            # BuildSketch context manager returns the builder.
            # To get the object, we use .sketch or ensure we are passing the object.
            # sketch_compiler.py returns `bs` (the builder instance).
            # `extrude(sketch, amount=depth)` works if sketch is a Sketch/Face.
            
            # The builder object can be used if we access its `sketch` property or if `extrude` accepts it.
            # build123d `extrude` accepts `Compound`, `Sketch`, `Face`, `Wire`.
            # `bs.sketch` gives the underlying compound.
            
            target_geo = sketch.sketch if hasattr(sketch, "sketch") else sketch
            
            return extrude(target_geo, amount=depth)
            
        except Exception as e:
            raise FeatureCompilationError(
                f"Extrude failed for feature '{feature.id}': {e}"
            )
