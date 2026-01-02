from app.domain.feature_graph_v1 import FeatureGraphV1
from .sketch_compiler import SketchCompiler
from .feature_compiler import FeatureCompiler


class FeatureGraphCompilerV1:
    def __init__(self):
        self.sketch_compiler = SketchCompiler()
        self.feature_compiler = FeatureCompiler()

    def compile(self, graph: FeatureGraphV1):
        """
        Deterministically compiles a FeatureGraphV1 into a build123d solid.
        """
        # 1. Compile all sketches (2D)
        sketches = self.sketch_compiler.compile(graph)
        
        # 2. Compile features (3D) using the sketches
        solid = self.feature_compiler.compile(graph, sketches)
        
        return solid
