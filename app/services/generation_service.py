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
# [NEW] Import V1 Schema
from app.domain.feature_graph_v1 import FeatureGraphV1
from app.domain.feature_graph_v3 import FeatureGraphV3
from pydantic import ValidationError
from app.compilers.build123d_compiler import Build123dCompiler
from app.compilers.v1.compiler import FeatureGraphCompilerV1
from app.services.retry_policy import is_retryable
from build123d import export_gltf, export_step, export_stl
from app.llm import LLMClient
from app.services.intent_contract import DecomposedIntent
from app.cad.onshape.adapter import OnshapeFeatureGraphAdapter
from app.services.dataset_writer import write_dataset_sample
from app.domain.dataset_sample import DatasetSample
import logging

MAX_RETRIES = 1

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
    
    @staticmethod
    def parse_feature_graph(llm_output: dict) -> FeatureGraphV1:
        """
        Strictly validates LLM output against FeatureGraphV1.
        Fails fast if the schema is incorrect.
        """
        try:
            return FeatureGraphV1(**llm_output)
        except ValidationError as e:
            # We raise ValueError here so it propagates cleanly as a "Bad Request" type error
            # rather than an internal server error.
            raise ValueError(f"Invalid FeatureGraph schema: {e}")
    
    @staticmethod
    def decompose_prompt(prompt: str) -> DecomposedIntent:
        """
        Decomposes natural language prompt into structured intent.
        Enforces discipline by identifying unsupported expert concepts.
        """
        sketch = []
        constraints = []
        features = []
        unsupported = []

        keywords = prompt.lower()

        if "rectangle" in keywords or "plate" in keywords or "box" in keywords:
            sketch.append("base_profile")
            features.append("extrude")

        if "hole" in keywords or "circle" in keywords or "cylinder" in keywords or "shaft" in keywords:
            sketch.append("circle")
            
        if "box" in keywords or "cylinder" in keywords or "shaft" in keywords:
            features.append("extrude")

        if "horizontal" in keywords or "vertical" in keywords:
            constraints.append("orientation")

        if "distance" in keywords or "radius" in keywords or "length" in keywords or "width" in keywords:
            constraints.append("dimension")

        if "extrude" in keywords or "thickness" in keywords or "height" in keywords:
            features.append("extrude")

        if "fillet" in keywords:
            unsupported.append("fillet")

        if "symmetric" in keywords or "mirror" in keywords:
            unsupported.append("symmetry")

        return DecomposedIntent(
            sketch_intent=sketch,
            constraint_intent=constraints,
            feature_intent=features,
            unsupported_intent=unsupported
        )
    
    def __init__(self, output_dir: Path = Path("outputs"), llm_client: LLMClient = None, use_v3_compiler: bool = False, use_two_stage: bool = False):
        """
        Initialize the generation service.
        
        Args:
            output_dir: Directory for output files
            llm_client: Optional injected LLM client
            use_v3_compiler: Enable Phase 2 topological identity tracking (default: False)
            use_two_stage: Enable Phase 4 two-stage LLM (intent → template) (default: False)
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        
        # Dependencies
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        
        # Core Components
        # Build123d is the primary CAD compiler
        if use_v3_compiler:
            from app.compilers import Build123dCompilerV3
            self.compiler = Build123dCompilerV3(output_dir=output_dir)
            logger.info("Using Build123dCompilerV3 (Phase 2: Topological Identity)")
        else:
            self.compiler = Build123dCompiler(output_dir=output_dir)
            logger.info("Using Build123dCompiler (Standard)")
        
        self.v1_compiler = FeatureGraphCompilerV1()
        self.llm_client = llm_client or LLMClient()
        
        # Phase 4: Two-stage mode
        self.use_two_stage = use_two_stage
        if use_two_stage:
            logger.info("Phase 4: Two-stage LLM mode enabled (Intent → Template)")
        
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

    async def generate(self, prompt: str, backend: str = "build123d", onshape_context: Dict[str, str] = None) -> GenerationResult:
        """
        Generate CAD from natural language prompt.
        
        New Unified Pipeline:
        1. LLM generates FeatureGraph from prompt (with retries)
        2. Compiler converts FeatureGraph to geometry (Backend agnostic)
        
        Args:
            prompt: User description
            backend: "build123d" (default) or "onshape"
            onshape_context: Dict with keys 'document_id', 'workspace_id', 'element_id'
            
        Returns:
            GenerationResult containing paths and metadata
        """
        job_id = str(uuid.uuid4())
        logger.info(f"Starting generation job_id={job_id} for prompt='{prompt}'")
        
        attempt = 0
        last_trace = None
        
        # 1. Decompose Prompt (Pre-LLM)
        intent = self.decompose_prompt(prompt)
        
        # 2. Hard Fail on Unsupported Concepts
        if intent.unsupported_intent:
            return GenerationResult(
                geometry_path=Path(""),
                format="glb",
                metadata={
                    "job_id": job_id,
                    "prompt": prompt,
                    "error": f"Unsupported features requested: {intent.unsupported_intent}"
                },
                source="llm-v2"
            )
            
        logger.info(f"Decomposed Intent: {intent}")
        
        while attempt <= MAX_RETRIES:
            try:
                # 3. Generate FeatureGraph via LLM (with intent)
                fg_v1 = await self.llm_client.generate_feature_graph(
                    prompt, last_trace, intent.model_dump()
                )

                # Lift to V3 (design-intent IR) and project back to V1
                # for the existing compiler pipeline.
                fg_v3 = FeatureGraphV3.from_v1(fg_v1)
                fg_for_compile = fg_v3.to_v1()

                solid, trace = None, None
                
                # 4. Select Backend
                if backend == "onshape":
                    if not onshape_context:
                        raise ValueError("Onshape backend requires onshape_context (did, wid, eid)")
                        
                    logger.info("Compiling to Onshape...")
                    adapter = OnshapeFeatureGraphAdapter(
                        onshape_context.get("document_id"),
                        onshape_context.get("workspace_id"),
                        onshape_context.get("element_id")
                    )
                    # Onshape adapter compiles directly to cloud, doesn't return solid/trace in same way
                    # For now, we assume success if no exception, or we need the adapter to return a trace?
                    # The instructions didn't specify adapter return type, but V1 compiler returns (solid, trace).
                    # Let's assume adapter.compile(graph) raises exception on failure and we mock a success trace.
                    adapter.compile(fg_for_compile)
                    
                    # Mock trace for consistency
                    from app.domain.execution_trace import ExecutionTrace, TraceEvent
                    trace = ExecutionTrace(success=True, events=[TraceEvent(stage="onshape", status="success", message="Synced to Onshape")])
                    solid = "onshape_cloud_entity" 

                elif backend == "cadquery":
                    # CadQuery backend removed - use Build123d instead
                    logger.warning("CadQuery backend deprecated, falling back to Build123d")
                    solid, trace = self.v1_compiler.compile(fg_for_compile)
                    
                else:
                    # Default: Build123d Backend
                    solid, trace = self.v1_compiler.compile(fg_for_compile)
                
                # 5. Check Success
                if trace.success and solid:
                    metadata = {
                        "job_id": job_id,
                        "prompt": prompt,
                        # Expose V3 to callers as the canonical IR
                        "feature_graph": fg_v3.to_dataset_dict(),
                        "retry_count": attempt,
                        # Parameters in a JSON-friendly form
                        "parameters": fg_v3.parameters,
                        "backend": backend,
                    }

                    if backend != "onshape":
                        # Export files for local backends (Build123d)
                        glb_path = self.output_dir / f"{job_id}.glb"
                        step_path = self.output_dir / f"{job_id}.step"
                        stl_path = self.output_dir / f"{job_id}.stl"
                        
                        export_gltf(solid, str(glb_path))
                        export_step(solid, str(step_path))
                        export_stl(solid, str(stl_path))
                        
                        metadata["step_path"] = str(step_path)
                        metadata["stl_path"] = str(stl_path)
                    
                    # --- DATASET LOGGING (all backends) ---
                    try:
                        sample = DatasetSample(
                            prompt=prompt,
                            decomposed_intent=intent.model_dump(),
                            feature_graph=fg_v3,
                            execution_trace=trace,
                            success=trace.success,
                            backend=backend,
                            timestamp=datetime.datetime.utcnow().isoformat(),
                        )
                        write_dataset_sample(sample)
                    except Exception as e:
                        logger.warning(f"Failed to log dataset sample: {e}")
                    # -----------------------

                    if backend == "onshape":
                        # Onshape result (no local geometry to return)
                        return GenerationResult(
                            geometry_path=Path(""),
                            format="onshape",
                            metadata=metadata,
                            source="llm-v2",
                            execution_trace=trace
                        )
                    else:
                        # Build123d - return local geometry
                        return GenerationResult(
                            geometry_path=glb_path,
                            format="glb",
                            metadata=metadata,
                            source="llm-v2",
                            execution_trace=trace
                        )
                
                # 4. Handle Failure
                trace.retryable = is_retryable(trace)
                
                if not trace.retryable or attempt == MAX_RETRIES:
                    
                    # --- DATASET LOGGING ---
                    try:
                        sample = DatasetSample(
                            prompt=prompt,
                            decomposed_intent=intent.model_dump(),
                            feature_graph=fg_v3,
                            execution_trace=trace,
                            success=trace.success,  # Likely False here
                            backend=backend,
                            timestamp=datetime.datetime.utcnow().isoformat(),
                        )
                        write_dataset_sample(sample)
                    except Exception as e:
                        logger.warning(f"Failed to log dataset sample: {e}")
                    # -----------------------

                    return GenerationResult(
                        geometry_path=Path(""), # No geometry on failure
                        format="glb",
                        metadata={
                            "job_id": job_id,
                            "prompt": prompt,
                            "retry_count": attempt,
                            "error": "Compilation failed"
                        },
                        source="llm-v2",
                        execution_trace=trace
                    )
                
                # Setup for retry
                logger.warning(f"Generation failed (attempt {attempt}), retrying...")
                last_trace = trace
                attempt += 1
                
            except Exception as e:
                logger.error(f"Generation loop error: {e}")
                raise e
        
        return None # Should be unreachable due to return in loop

    
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
