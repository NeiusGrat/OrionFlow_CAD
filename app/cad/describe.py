from app.domain.feature_graph import FeatureGraph

def describe_feature_graph(graph: FeatureGraph) -> str:
    """
    Deterministic description of the Feature Graph.
    """
    lines = []
    
    lines.append(f"Part Type: {graph.part_type.title()}")
    lines.append(f"Base Plane: {graph.base_plane}")
    
    for i, feature in enumerate(graph.features, 1):
        line = f"{i}. Feature '{feature.type}'"
        
        # Add ID if useful? No, keep it English.
        
        params_str = ", ".join(f"{k}={v}" for k, v in feature.params.items())
        if params_str:
            line += f" with {params_str}"
            
        lines.append(line)
        
    return "\n".join(lines)
