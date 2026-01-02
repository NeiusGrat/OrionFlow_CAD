import sys
from app.domain.feature_graph_v1 import FeatureGraphV1
from app.compilers.v1.compiler import FeatureGraphCompilerV1

graph = FeatureGraphV1(
    schema_version="1.0",
    units="mm",
    metadata={"intent": "bad graph"},
    parameters={},
    sketches=[],
    features=[]
)

solid, trace = FeatureGraphCompilerV1().compile(graph)

print(f"solid: {solid}")
print(f"trace.success: {trace.success}")
print(f"trace.events: {trace.events}")
for event in trace.events:
    print(f"  {event}")
