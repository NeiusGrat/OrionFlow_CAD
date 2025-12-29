"""
Generation Service Layer - Orchestrates CAD generation pipelines.
Isolates business logic from HTTP routing layer.
"""
import uuid
import datetime
import json
from pathlib import Path
from typing import Tuple, Dict, Any

from app.intent.intent_parser import parse_intent
import app.ml.parameter_infer as infer_rules
from app.validation.sanity import validate
from app.domain.generation_result import GenerationResult
from app.domain.feature_graph import FeatureGraph, Feature
from app.compilers.build123d_compiler import Build123dCompiler

# Legacy imports (deprecated - not used in active path)
# from app.cad.registry import PART_REGISTRY
# from app.cad.legacy.cq_builder import build_from_graph
# from cadquery import exporters
import trimesh


class GenerationService:
    """
    Orchestrates CAD generation pipelines (V1 and V2).
    Isolates business logic from HTTP layer for better testability.
    """
    
    def __init__(self, output_dir: Path = Path("outputs")):
        """
        Initialize the generation service.
        
        Args:
            output_dir: Directory for output files
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        
        # NEW: Build123d Compiler (replaces CadQuery)
        self.compiler = Build123dCompiler(output_dir=output_dir)
    
    def generate(self, prompt: str) -> Tuple[GenerationResult, Dict[str, Any]]:
        """
        Unified generation method (replaces V1/V2).
        
        This is the new canonical entry point for CAD generation.
        Internally delegates to existing builders for now, but provides
        a single interface for future LLM → FeatureGraph → Export pipeline.
        
        Args:
            prompt: User's text description
            
        Returns:
            Tuple of (GenerationResult, debug_info) for backward compatibility
            
        Raises:
            ValueError: If generation fails
            Exception: If geometry generation fails
        """
        # For now, delegate to V1 pipeline
        # Future: LLM → FeatureGraph → Exporters
        return self.generate_v1(prompt)
    
    def generate_v1(self, prompt: str) -> Tuple[GenerationResult, Dict[str, Any]]:
        """
        V1 Pipeline: Intent → Parameters → Geometry
        
        DEPRECATED: Use generate() instead. This will be removed in future versions.
        
        Args:
            prompt: User's text description
            
        Returns:
            Tuple of (GenerationResult, debug_info)
            
        Raises:
            ValueError: If intent parsing fails or confidence too low
            Exception: If geometry generation fails
        """
        job_id = str(uuid.uuid4())
        
        # 1. Parse Intent (Locked) & Confidence
        intent, confidence = parse_intent(prompt)
        print(f"DEBUG: Intent={intent} Confidence={confidence}")
        
        # Hard fail on ambiguity
        if confidence < 0.7:
            raise ValueError(
                "I'm not sure what you want to make. "
                "Please be more specific (e.g. 'box', 'cylinder')."
            )
        
        # 2. Infer Parameters: Rule-Based (with intelligent defaults)
        # XGBoost removed - rules now handle both explicit and implicit params
        # LLM will provide better inference in future iterations
        final_params, param_units = infer_rules.infer_parameters(intent, prompt)
        
        print(f"DEBUG: Params={final_params}")
        
        # 3. Validate (Fail Fast)
        validate(final_params, intent)
        
        # 4. Build FeatureGraph from intent and parameters
        feature_graph = self._build_feature_graph_from_intent(
            intent.part_type, final_params
        )
        
        # 5. Compile geometry using Build123d (NEW: Clean separation)
        step_path, stl_path, glb_path = self.compiler.compile(feature_graph, job_id)
        
        # 6. Build Result
        result = GenerationResult(
            geometry_path=glb_path,
            format="glb",
            metadata={
                "job_id": job_id,
                "prompt": prompt,
                "parameters": final_params,
                "intent": intent.model_dump()
            },
            source="v1"
        )
        
        # 7. Debug info for backward compatibility
        debug_info = {
            "step_path": step_path,
            "stl_path": stl_path,
            "param_units": param_units,
            "feature_graph": self._build_mock_feature_graph(
                intent.part_type, final_params, param_units, job_id
            )
        }
        
        return result, debug_info
    
    def generate_v2(self, glb_bytes: bytes, metadata: Dict[str, Any]) -> GenerationResult:
        """
        V2 Pipeline: LLM → Code → Geometry (GLB bytes already generated)
        This wraps the existing V2 flow into the unified contract.
        
        DEPRECATED: Use generate() instead. This will be removed in future versions.
        
        Args:
            glb_bytes: Generated GLB file bytes
            metadata: Additional metadata (prompt, etc.)
            
        Returns:
            GenerationResult with V2 source
        """
        job_id = str(uuid.uuid4())
        glb_path = self.output_dir / f"{job_id}.glb"
        glb_path.write_bytes(glb_bytes)
        
        return GenerationResult(
            geometry_path=glb_path,
            format="glb",
            metadata={
                "job_id": job_id,
                **metadata
            },
            source="v2"
        )
    
    def regenerate(self, feature_graph_dict: dict, prompt: str = "") -> GenerationResult:
        """
        Regenerate from edited feature graph (V1 parametric editing).
        
        Args:
            feature_graph_dict: Feature graph dictionary from frontend
            prompt: Optional prompt context for feedback logging
            
        Returns:
            GenerationResult with regenerated geometry
            
        Raises:
            Exception: If graph is invalid or build fails
        """
        job_id = str(uuid.uuid4())
        
        # 1. Rehydrate Graph
        graph = FeatureGraph(**feature_graph_dict)
        
        # 2. Compile geometry using Build123d
        step_path, stl_path, glb_path = self.compiler.compile(graph, job_id)
        
        # 3. Active Learning: Log Feedback
        flattened_params = {}
        for f in graph.features:
            flattened_params.update(f.params)
        
        self._log_feedback(prompt, flattened_params, graph.part_type)
        
        return GenerationResult(
            geometry_path=glb_path,
            format="glb",
            metadata={
                "job_id": job_id,
                "prompt": prompt,
                "feature_graph": graph.model_dump(),
                "step_path": str(step_path),
                "stl_path": str(stl_path)
            },
            source="v1"
        )
    
    def _build_feature_graph_from_intent(self, part_type: str, params: dict) -> FeatureGraph:
        """
        Build FeatureGraph from intent and parameters.
        
        Converts legacy intent-based parameters into canonical FeatureGraph format.
        
        Args:
            part_type: Type of part (box, cylinder, shaft)
            params: Parameter dictionary
            
        Returns:
            FeatureGraph ready for compilation
        """
        if part_type == "box":
            return FeatureGraph(
                part_type="box",
                base_plane="XY",
                features=[
                    Feature(
                        id="sketch_1",
                        type="rectangle",
                        params={
                            "length": params.get("length", 10.0),
                            "width": params.get("width", 10.0)
                        },
                        depends_on=[]
                    ),
                    Feature(
                        id="extrude_1",
                        type="extrude",
                        params={"height": params.get("height", 10.0)},
                        depends_on=["sketch_1"]
                    )
                ]
            )
        elif part_type == "cylinder":
            return FeatureGraph(
                part_type="cylinder",
                base_plane="XY",
                features=[
                    Feature(
                        id="sketch_1",
                        type="circle",
                        params={"radius": params.get("radius", 5.0)},
                        depends_on=[]
                    ),
                    Feature(
                        id="extrude_1",
                        type="extrude",
                        params={"height": params.get("height", 10.0)},
                        depends_on=["sketch_1"]
                    )
                ]
            )
        elif part_type == "shaft":
            return FeatureGraph(
                part_type="shaft",
                base_plane="XY",
                features=[
                    Feature(
                        id="sketch_1",
                        type="circle",
                        params={"radius": params.get("radius", 2.5)},
                        depends_on=[]
                    ),
                    Feature(
                        id="extrude_1",
                        type="extrude",
                        params={"height": params.get("height", 50.0)},
                        depends_on=["sketch_1"]
                    )
                ]
            )
        else:
            raise ValueError(f"Unsupported part type: {part_type}")
    
    @staticmethod
    def _convert_stl_to_glb(stl_path: Path, glb_path: Path):
        """
        Convert STL mesh to GLB for browser visualization.
        
        DEPRECATED: Compiler now handles this directly.
        Kept for regenerate() backward compatibility.
        
        Args:
            stl_path: Input STL file path
            glb_path: Output GLB file path
        """
        mesh = trimesh.load_mesh(stl_path)
        glb_bytes = mesh.export(file_type="glb")
        glb_path.write_bytes(glb_bytes)
    
    @staticmethod
    def _build_mock_feature_graph(part_type: str, params: dict, units: dict, job_id: str) -> dict:
        """
        Build mock feature graph for backward compatibility with frontend.
        
        Args:
            part_type: Type of part
            params: Parameters dictionary
            units: Units dictionary
            job_id: Job identifier
            
        Returns:
            Mock feature graph dictionary
        """
        return {
            "part_type": part_type,
            "features": [{
                "type": part_type,
                "params": params,
                "units": units,
                "name": "Main Shape",
                "id": str(uuid.uuid4())
            }]
        }
    
    @staticmethod
    def _log_feedback(prompt: str, final_params: dict, part_type: str):
        """
        Log user edits for Active Learning.
        
        Args:
            prompt: User prompt
            final_params: Final parameters after editing
            part_type: Type of part
        """
        if not prompt:
            return
        
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "prompt": prompt,
            "part_type": part_type,
            "params": final_params
        }
        
        try:
            with open("data/feedback.jsonl", "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Warning: Failed to log feedback: {e}")
