"""
Generation Service Layer - Orchestrates CAD generation pipelines.
Isolates business logic from HTTP routing layer.
"""
import uuid
import datetime
import json
from pathlib import Path
from typing import Tuple, Dict, Any


from app.domain.generation_result import GenerationResult
from app.domain.feature_graph import FeatureGraph, Feature
from app.compilers.build123d_compiler import Build123dCompiler
from app.llm import LLMClient
import logging

# Legacy imports (deprecated)
# from app.intent.intent_parser import parse_intent
# import app.ml.parameter_infer as infer_rules
# from app.validation.sanity import validate

logger = logging.getLogger(__name__)


class GenerationService:
    """
    Orchestrates CAD generation pipelines.
    
    Flow: Prompt → LLM (FeatureGraph) → Compiler → Geometry Files
    """
    
    def __init__(self, output_dir: Path = Path("outputs"), llm_client: LLMClient = None):
        """
        Initialize the generation service.
        
        Args:
            output_dir: Directory for output files
            llm_client: Optional injected LLM client
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        
        # Dependencies
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        
        # Core Components
        self.compiler = Build123dCompiler(output_dir=output_dir)
        self.llm_client = llm_client or LLMClient()
        
        # Onshape Integration (Optional - Live CAD)
        # We lazy-load these to avoid hard dependencies if keys are missing
        self.onshape_client = None
        self.onshape_compiler = None
        
        try:
            from app.clients.onshape_client import OnshapeClient
            from app.compilers.onshape_compiler import OnshapeCompiler
            
            client = OnshapeClient()
            if client.is_configured():
                self.onshape_client = client
                self.onshape_compiler = OnshapeCompiler()
                logger.info("Onshape integration enabled")
            else:
                logger.info("Onshape integration disabled (missing API keys)")
        except ImportError:
            logger.warning("Could not import Onshape components")

    async def sync_to_onshape(self, feature_graph: FeatureGraph, doc_id: str, work_id: str, ele_id: str) -> bool:
        """
        Push current design to Onshape (Step 5/6).
        
        Args:
            feature_graph: The design to sync
            doc_id: Onshape Document ID
            work_id: Onshape Workspace ID
            ele_id: Onshape Element ID (FeatureStudio)
            
        Returns:
            True if sync successful
        """
        if not self.onshape_client or not self.onshape_compiler:
            logger.warning("Cannot sync to Onshape: Not configured")
            return False
            
        try:
            # 1. Compile to FeatureScript (CFG -> FS)
            script_content = self.onshape_compiler.compile(feature_graph)
            
            # 2. Push to API
            return self.onshape_client.update_featurescript(
                did=doc_id,
                wid=work_id,
                eid=ele_id,
                script_content=script_content
            )
        except Exception as e:
            logger.error(f"Onshape sync failed: {e}")
            return False

    async def generate(self, prompt: str) -> GenerationResult:
        """
        Generate CAD from natural language prompt.
        
        New Unified Pipeline:
        1. LLM generates FeatureGraph from prompt
        2. Compiler converts FeatureGraph to geometry (STEP/STL/GLB)
        
        Args:
            prompt: User description (e.g., "box 10x10x10")
            
        Returns:
            GenerationResult containing paths and metadata
        """
        job_id = str(uuid.uuid4())
        logger.info(f"Starting generation job_id={job_id} for prompt='{prompt}'")
        
        # 1. Generate FeatureGraph via LLM
        # This replaces the old intent parser + rule-based inference
        feature_graph = await self.llm_client.generate_feature_graph(prompt)
        
        # 2. Compile geometry using Build123d
        step_path, stl_path, glb_path = self.compiler.compile(feature_graph, job_id)
        
        # 3. Build Result
        result = GenerationResult(
            geometry_path=glb_path,
            format="glb",
            metadata={
                "job_id": job_id,
                "prompt": prompt,
                "feature_graph": feature_graph.model_dump(),
                "step_path": str(step_path),
                "stl_path": str(stl_path)
            },
            source="llm-v2"
        )
        
        return result
    
    def generate_legacy(self, prompt: str) -> Tuple[GenerationResult, Dict[str, Any]]:
        """
        Legacy V1 Generation Pipeline (Rules-Based).
        
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
    
    async def regenerate(self, feature_graph_dict: dict, prompt: str = "") -> GenerationResult:
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
        
        # 1. Rehydrate Graph (Validate CFG v1)
        graph = FeatureGraph(**feature_graph_dict)
        
        # 2. Compile geometry using Build123d (Local)
        step_path, stl_path, glb_path = self.compiler.compile(graph, job_id)
        
        # 3. Sync to Onshape (Cloud - Live CAD)
        # Check for environment variables for the "Live" document target
        # In production, these might come from the request
        import os
        did = os.getenv("ONSHAPE_DOC_ID")
        wid = os.getenv("ONSHAPE_WORKSPACE_ID")
        eid = os.getenv("ONSHAPE_ELEMENT_ID")
        
        if did and wid and eid:
             logger.info(f"Syncing job {job_id} to Onshape...")
             success = await self.sync_to_onshape(graph, did, wid, eid)
             if success:
                 logger.info("Onshape sync completed.")
             else:
                 logger.warning("Onshape sync failed.")
        
        # 4. Active Learning: Log Feedback
        try:
            flattened_params = {}
            # Handle list-based parameters structure if needed, or simple dict
            # Graph parameters is Dict[str, float] in v1
            flattened_params.update(graph.parameters)
            self._log_feedback(prompt, flattened_params, "custom")
        except Exception as e:
            logger.warning(f"Feedback logging failed: {e}")
        
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
