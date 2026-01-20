
from pathlib import Path
from uuid import uuid4
from app.domain.feature_graph_v2 import FeatureGraphV2, FeatureV2, SketchGraphV2, SketchPrimitiveV2, SemanticSelector, SelectorType
from app.compilers.build123d_compiler_v3 import Build123dCompilerV3
from app.compilers.v1.errors import FeatureCompilationError

def debug_valid_geometry_passes():
    print("Running debug_valid_geometry_passes...")
    graph = FeatureGraphV2(
        version="2.0",
        units="mm",
        parameters={"width": 50, "depth": 30, "height": 20, "fillet_r": 2},
        sketches=[
            SketchGraphV2(
                id="s1",
                plane="XY",
                primitives=[
                    SketchPrimitiveV2(
                        id="p1",
                        type="rectangle",
                        params={"width": "$width", "height": "$depth"}
                    )
                ]
            )
        ],
        features=[
            FeatureV2(id="extrude_1", type="extrude", sketch="s1", params={"depth": "$height"}),
            FeatureV2(
                id="fillet_1",
                type="fillet",
                params={"radius": "$fillet_r"},
                topology_refs={
                    "edges": SemanticSelector(
                        selector_type=SelectorType.STRING,
                        string_selector=">Z"
                    )
                }
            )
        ]
    )
    
    compiler = Build123dCompilerV3(Path("outputs"))
    job_id = f"test_{uuid4().hex[:8]}"
    
    try:
        compiler.compile(graph, job_id)
        print("Success!")
    except FeatureCompilationError as e:
        print(f"Caught Error: {e}")
        if e.compiler_error:
            print(f"CompilerError: {e.compiler_error.reason}")

if __name__ == "__main__":
    debug_valid_geometry_passes()
