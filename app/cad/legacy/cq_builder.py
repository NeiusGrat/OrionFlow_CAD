import cadquery as cq
from app.cad.feature_graph import FeatureGraph, Feature
from typing import List

def topological_sort(features: List[Feature]) -> List[Feature]:
    """
    Sorts features so that dependencies are processed first.
    """
    feature_map = {f.id: f for f in features}
    adj = {f.id: set(f.depends_on) for f in features}
    
    sorted_features = []
    
    # Simple Kahn's algorithm or iterative
    # Since graph is small, we iterate
    processed = set()
    
    while len(processed) < len(features):
        progress = False
        for f in features:
            if f.id in processed:
                continue
                
            # Check if all dependencies are processed
            deps = adj[f.id]
            if deps.issubset(processed):
                sorted_features.append(f)
                processed.add(f.id)
                progress = True
        
        if not progress:
            raise ValueError("Circular dependency or missing dependency detected")
            
    return sorted_features

def enforce_constraints(graph: FeatureGraph):
    """
    Clamps parameters based on constraints.
    """
    for feature in graph.features:
        if not feature.constraints:
            continue
            
        min_val = feature.constraints.get("min")
        max_val = feature.constraints.get("max")
        
        for key, val in feature.params.items():
            if isinstance(val, (int, float)):
                if min_val is not None:
                    feature.params[key] = max(min_val, val)
                if max_val is not None:
                    feature.params[key] = min(max_val, feature.params[key])

def build_from_graph(graph: FeatureGraph):
    """
    Build CadQuery geometry from feature graph.
    """
    # 1. Constraints
    enforce_constraints(graph)
    
    # 2. Topological Sort
    sorted_features = topological_sort(graph.features)
    
    # 3. Execution
    wp = cq.Workplane(graph.base_plane)

    for feature in sorted_features:
        if feature.type == "circle":
            wp = wp.circle(feature.params["radius"])
            
        elif feature.type == "rectangle":
            wp = wp.rect(feature.params["length"], feature.params["width"])

        elif feature.type == "extrude":
            wp = wp.extrude(feature.params["height"])

        else:
            raise ValueError(f"Unsupported feature: {feature.type}")

    return wp
