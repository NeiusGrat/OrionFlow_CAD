from build123d import *
from app.domain.feature_graph_v1 import FeatureGraphV1, SketchGraph
from .errors import SketchCompilationError


class SketchCompiler:
    def compile(self, graph: FeatureGraphV1):
        sketches = {}

        for sketch in graph.sketches:
            sketches[sketch.id] = self._compile_single_sketch(sketch, graph)

        return sketches

    def _compile_single_sketch(self, sketch: SketchGraph, graph: FeatureGraphV1):
        try:
            # Map string to Build123d Plane
            plane_map = {
                "XY": Plane.XY,
                "YZ": Plane.YZ,
                "XZ": Plane.XZ
            }
            target_plane = plane_map.get(sketch.plane, Plane.XY)
            
            with BuildSketch(target_plane) as bs:
                self._add_primitives(bs, sketch, graph)
                self._add_constraints(bs, sketch, graph)
            return bs
        except Exception as e:
            raise SketchCompilationError(
                f"Failed to compile sketch '{sketch.id}': {e}"
            )

    def _add_primitives(self, bs, sketch: SketchGraph, graph: FeatureGraphV1):
        for prim in sketch.primitives:
            if prim.type == "rectangle":
                self._add_rectangle(bs, prim, graph)
            elif prim.type == "circle":
                self._add_circle(bs, prim, graph)
            else:
                raise SketchCompilationError(
                    f"Unsupported primitive type: {prim.type}"
                )

    def _resolve_param(self, value, graph: FeatureGraphV1):
        if isinstance(value, str):
            # Check if it refers to a parameter (e.g., "$width" or just "width")
            # The prompt examples show "$width", but the schema says value is Union[str, float].
            # The test case uses "width" directly without $.
            # Let's handle both for robustness, or strictly follow the test case.
            # The test case: "params": {"width": "w"} where "w" is a key in parameters.
            
            clean_val = value.lstrip("$") # Handle $ prefix if present
            if clean_val in graph.parameters:
                return graph.parameters[clean_val].value
                
            # If not in parameters, it might be a literal string? 
            # But primitives types expect numbers.
            # If it's a number string "10", we try float.
            try:
                return float(value)
            except ValueError:
                pass
                
        return value

    def _add_rectangle(self, bs, prim, graph):
        # params: width, height
        current_params = prim.params
        width = self._resolve_param(current_params["width"], graph)
        height = self._resolve_param(current_params["height"], graph)
        Rectangle(width, height)

    def _add_circle(self, bs, prim, graph):
        current_params = prim.params
        radius = self._resolve_param(current_params["radius"], graph)
        Circle(radius)

    def _add_constraints(self, bs, sketch, graph):
        # Constraints will be implemented in Step 3
        pass
