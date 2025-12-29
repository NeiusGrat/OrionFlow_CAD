"""
Build123d Compiler - FeatureGraph → STEP/STL/GLB

This is the NEW canonical geometry compiler.
Replaces: generation_engine.py, cq_builder.py, registry.py, base_part.py
"""
from pathlib import Path
from typing import Tuple
import trimesh

from app.domain.feature_graph import FeatureGraph, Feature
from build123d import *


class Build123dCompiler:
    """
    Compiles FeatureGraph to actual geometry using Build123d.
    
    Input: FeatureGraph (domain model)
    Output: STEP, STL, GLB files
    """
    
    def __init__(self, output_dir: Path = Path("outputs")):
        """
        Initialize the Build123d compiler.
        
        Args:
            output_dir: Directory for output files
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
    
    def compile(self, feature_graph: FeatureGraph, job_id: str) -> Tuple[Path, Path, Path]:
        """
        Compile FeatureGraph to geometry files.
        
        Args:
            feature_graph: The canonical feature graph
            job_id: Unique identifier for this generation
            
        Returns:
            Tuple of (step_path, stl_path, glb_path)
            
        Raises:
            ValueError: If feature graph is invalid
            Exception: If compilation fails
        """
        # 1. Build geometry from feature graph
        geometry = self._build_from_graph(feature_graph)
        
        # 2. Export to all formats
        step_path = self.output_dir / f"{job_id}.step"
        stl_path = self.output_dir / f"{job_id}.stl"
        glb_path = self.output_dir / f"{job_id}.glb"
        
        # Export STEP
        geometry.export_step(str(step_path))
        
        # Export STL
        geometry.export_stl(str(stl_path))
        
        # Convert STL to GLB for web viewer
        self._convert_stl_to_glb(stl_path, glb_path)
        
        return step_path, stl_path, glb_path
    
    def _build_from_graph(self, graph: FeatureGraph):
        """
        Build Build123d geometry from FeatureGraph.
        
        Args:
            graph: Feature graph to compile
            
        Returns:
            Build123d Part object
        """
        # Topological sort to handle dependencies
        sorted_features = self._topological_sort(graph.features)
        
        # Build geometry based on part type
        if graph.part_type == "box":
            return self._build_box(sorted_features)
        elif graph.part_type == "cylinder":
            return self._build_cylinder(sorted_features)
        elif graph.part_type == "shaft":
            return self._build_shaft(sorted_features)
        else:
            raise ValueError(f"Unsupported part type: {graph.part_type}")
    
    def _build_box(self, features: list[Feature]):
        """Build a box from features."""
        # Extract rectangle and extrude features
        rect_feature = next((f for f in features if f.type == "rectangle"), None)
        extrude_feature = next((f for f in features if f.type == "extrude"), None)
        
        if not rect_feature or not extrude_feature:
            raise ValueError("Box requires rectangle and extrude features")
        
        length = rect_feature.params.get("length", 10.0)
        width = rect_feature.params.get("width", 10.0)
        height = extrude_feature.params.get("height", 10.0)
        
        with BuildPart() as box_part:
            Box(length, width, height)
        
        return box_part.part
    
    def _build_cylinder(self, features: list[Feature]):
        """Build a cylinder from features."""
        circle_feature = next((f for f in features if f.type == "circle"), None)
        extrude_feature = next((f for f in features if f.type == "extrude"), None)
        
        if not circle_feature or not extrude_feature:
            raise ValueError("Cylinder requires circle and extrude features")
        
        radius = circle_feature.params.get("radius", 5.0)
        height = extrude_feature.params.get("height", 10.0)
        
        with BuildPart() as cyl_part:
            Cylinder(radius=radius, height=height)
        
        return cyl_part.part
    
    def _build_shaft(self, features: list[Feature]):
        """Build a shaft (stepped cylinder) from features."""
        # Shaft is typically two stacked cylinders
        # For now, build single cylinder (can be extended)
        circle_features = [f for f in features if f.type == "circle"]
        extrude_features = [f for f in features if f.type == "extrude"]
        
        if not circle_features or not extrude_features:
            raise ValueError("Shaft requires circle and extrude features")
        
        # Use first circle/extrude pair
        radius = circle_features[0].params.get("radius", 2.5)
        height = extrude_features[0].params.get("height", 50.0)
        
        with BuildPart() as shaft_part:
            Cylinder(radius=radius, height=height)
        
        return shaft_part.part
    
    def _topological_sort(self, features: list[Feature]) -> list[Feature]:
        """
        Sort features by dependency order.
        
        Args:
            features: List of features to sort
            
        Returns:
            Sorted list of features
        """
        sorted_features = []
        processed = set()
        
        while len(processed) < len(features):
            progress = False
            for feature in features:
                if feature.id in processed:
                    continue
                
                # Check if all dependencies are processed
                deps = set(feature.depends_on)
                if deps.issubset(processed):
                    sorted_features.append(feature)
                    processed.add(feature.id)
                    progress = True
            
            if not progress:
                raise ValueError("Circular dependency or missing dependency detected")
        
        return sorted_features
    
    @staticmethod
    def _convert_stl_to_glb(stl_path: Path, glb_path: Path):
        """
        Convert STL to GLB for web viewer.
        
        Args:
            stl_path: Input STL file
            glb_path: Output GLB file
        """
        mesh = trimesh.load_mesh(stl_path)
        glb_bytes = mesh.export(file_type="glb")
        glb_path.write_bytes(glb_bytes)
