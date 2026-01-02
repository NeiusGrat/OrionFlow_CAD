from build123d import *
from app.domain.feature_graph_v1 import FeatureGraphV1, SketchGraph
from .errors import SketchCompilationError
import logging

logger = logging.getLogger(__name__)

# Stub constraints if missing in build123d environment
if "Coincident" not in globals():
    class Coincident:
        def __init__(self, *args):
            logger.warning("Coincident constraint not supported in this build123d version")

if "Horizontal" not in globals():
    class Horizontal:
        def __init__(self, *args):
            logger.warning("Horizontal constraint not supported in this build123d version")

if "Vertical" not in globals():
    class Vertical:
        def __init__(self, *args):
            logger.warning("Vertical constraint not supported in this build123d version")

if "Distance" not in globals():
    class Distance:
        def __init__(self, *args):
            logger.warning("Distance constraint not supported in this build123d version")

if "Radius" not in globals():
    class Radius:
        def __init__(self, *args):
            logger.warning("Radius constraint not supported in this build123d version")


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
                # Initialize local entity registry for this sketch
                self._entity_registry = {}
                
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
            clean_val = value.lstrip("$") # Handle $ prefix if present
            if clean_val in graph.parameters:
                return graph.parameters[clean_val].value
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
        
        # Create Primitive
        rect = Rectangle(width, height)
        
        # Register Entities (Center, Edges)
        # Note: We rely on standard build123d selection filters
        self._entity_registry[f"{prim.id}.center"] = rect.center()
        # For a standard centered rectangle:
        # X Axis Edges: Top/Bottom? No, Edges parallel to X.
        # Let's register "left", "right", "top", "bottom".
        # Edges sorted by center position usually works.
        sorted_x = rect.edges().sort_by(Axis.X)
        self._entity_registry[f"{prim.id}.left"] = sorted_x[0]
        self._entity_registry[f"{prim.id}.right"] = sorted_x[-1]
        
        sorted_y = rect.edges().sort_by(Axis.Y)
        self._entity_registry[f"{prim.id}.bottom"] = sorted_y[0]
        self._entity_registry[f"{prim.id}.top"] = sorted_y[-1]
        
        # Also register the object itself just in case
        self._entity_registry[prim.id] = rect

    def _add_circle(self, bs, prim, graph):
        current_params = prim.params
        radius = self._resolve_param(current_params["radius"], graph)
        
        circle = Circle(radius)
        
        # Register Entities
        self._entity_registry[f"{prim.id}.center"] = circle.center()
        self._entity_registry[f"{prim.id}.radius"] = radius # Value, not entity, but might be needed? 
        # Constraints generally act on Geometry.
        # Radius constraint acts on the object.
        self._entity_registry[prim.id] = circle

    def _add_constraints(self, bs, sketch, graph):
        for constraint in sketch.constraints:
            if constraint.type == "coincident":
                self._coincident(constraint)
            elif constraint.type == "horizontal":
                self._horizontal(constraint)
            elif constraint.type == "vertical":
                self._vertical(constraint)
            elif constraint.type == "distance":
                self._distance(constraint, graph)
            elif constraint.type == "radius":
                self._radius(constraint, graph)
            else:
                raise SketchCompilationError(
                    f"Unsupported constraint type: {constraint.type}"
                )

    def _get_entity(self, key):
        if key not in self._entity_registry:
             raise SketchCompilationError(f"Entity not found: {key}")
        return self._entity_registry[key]

    def _coincident(self, constraint):
        a, b = constraint.entities
        # build123d Coincident() takes Objects
        Coincident(
            self._get_entity(a),
            self._get_entity(b)
        )

    def _horizontal(self, constraint):
        (entity,) = constraint.entities
        Horizontal(self._get_entity(entity))

    def _vertical(self, constraint):
        (entity,) = constraint.entities
        Vertical(self._get_entity(entity))

    def _distance(self, constraint, graph):
        # usually 2 entities, or can be point to line
        a, b = constraint.entities
        value = constraint.value
        val = self._resolve_param(value, graph)

        Distance(
            self._get_entity(a),
            self._get_entity(b),
            val
        )

    def _radius(self, constraint, graph):
        (entity,) = constraint.entities
        value = constraint.value
        val = self._resolve_param(value, graph)

        Radius(
            self._get_entity(entity),
            val
        )
