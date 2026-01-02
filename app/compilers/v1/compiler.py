from app.domain.feature_graph_v1 import FeatureGraphV1
from app.domain.execution_trace import ExecutionTrace, TraceEvent
from .sketch_compiler import SketchCompiler
from .feature_compiler import FeatureCompiler


class FeatureGraphCompilerV1:
    def __init__(self):
        self.sketch_compiler = SketchCompiler()
        self.feature_compiler = FeatureCompiler()

    def compile(self, graph: FeatureGraphV1):
        """
        Deterministically compiles a FeatureGraphV1 into a build123d solid.
        
        Returns:
            Tuple of (solid, execution_trace)
        """
        trace = []
        
        try:
            # 1. Compile all sketches (2D)
            sketches = self.sketch_compiler.compile(graph)
            trace.append(TraceEvent(
                stage="sketch_compile",
                target=None,
                status="success"
            ))
            
            # 2. Compile features (3D) using the sketches
            solid = self.feature_compiler.compile(graph, sketches)
            trace.append(TraceEvent(
                stage="feature_compile",
                target=None,
                status="success"
            ))
            
            return solid, ExecutionTrace(
                success=True,
                events=trace
            )
            
        except Exception as e:
            trace.append(TraceEvent(
                stage="compile",
                target=None,
                status="failure",
                message=str(e)
            ))
            return None, ExecutionTrace(
                success=False,
                events=trace
            )
