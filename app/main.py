import os
import json
import uuid
import datetime
from pathlib import Path

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import cadquery as cq
from cadquery import exporters

from dotenv import load_dotenv

import trimesh

# New Architecture Imports
from app.intent.intent_parser import parse_intent
from app.ml.predictor_xgb import infer_parameters_xgb
import app.ml.parameter_infer as infer_rules
from app.validation.sanity import validate, stress_test
from app.cad.registry import PART_REGISTRY

# Legacy imports for Regenerate (keeping for back-compat if needed, though regenerate might need updates)
# from app.ml.predictor import predict_parameters 
# from app.ml.rules import infer_part_type
# from app.cad.graph_builder import build_cylinder_graph, build_box_graph, build_shaft_graph
from app.cad.cq_builder import build_from_graph
from app.cad.feature_graph import FeatureGraph
from app.cad.describe import describe_feature_graph

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


# Load environment variables from .env
load_dotenv()


ALLOWED_PARAMETERS = {
    "radius": {"min": 1, "max": 200, "default": 20},
    "height": {"min": 1, "max": 300, "default": 10}
}


app = FastAPI(
    title="OrionFlow CAD Engine",
    description="Text-to-Parametric CAD backend",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # Your Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# This makes http://127.0.0.1:8000/outputs/filename.stl work!
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


class GenerateRequest(BaseModel):
    prompt: str

class RegenerateRequest(BaseModel):
    feature_graph: dict
    prompt: str = "" # Optional prompt context for feedback logging

class DescribeRequest(BaseModel):
    feature_graph: dict

def convert_stl_to_glb(stl_path: Path, glb_path: Path):
    """
    Converts STL mesh to GLB for browser visualization.
    """
    mesh = trimesh.load_mesh(stl_path)
    glb_bytes = mesh.export(file_type="glb")
    glb_path.write_bytes(glb_bytes)

def log_feedback(prompt: str, final_params: dict, part_type: str):
    """
    Logs user edits for Active Learning.
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


@app.post("/generate")
def generate_cad(request: GenerateRequest):
    """
    Generate a CAD model from text (Prompt -> Intent -> Params -> Geometry)
    Now supports Multiple Part Types via 4-Layer Architecture!
    """
    job_id = str(uuid.uuid4())

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    step_path = output_dir / f"{job_id}.step"
    stl_path = output_dir / f"{job_id}.stl"
    glb_path = output_dir / f"{job_id}.glb"

    # 1. Parse Intent (Locked) & Confidence (Step 1 Robustness)
    try:
        intent, confidence = parse_intent(request.prompt)
        print(f"DEBUG: Intent={intent} Confidence={confidence}")
        
        # Hard fail on ambiguity (Step 1)
        if confidence < 0.7:
             # In a real assistant, this would return a "Clarification Request"
             # For now, we raise 400 with helpful message
             raise ValueError("I'm not sure what you want to make. Please be more specific (e.g. 'box', 'cylinder').")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    

    # 2. Infer Parameters: ROBUSTNESS CHECK (Step 1)
    # Run Rule-Based (Robust)
    rule_params, param_units = infer_rules.infer_parameters(intent, request.prompt)
    
    # Run ML-Based (Smart/Learning)
    ml_params = infer_parameters_xgb(intent, request.prompt)
    
    print(f"DEBUG: Rule Params={rule_params}")
    print(f"DEBUG: ML Params={ml_params}")

    # Compare ML vs Rules (Step 1: "If deviation > X% -> warn")
    # We use Rules as the 'Ground Truth' for generation because they handle explicit units/geometry strictly.
    # ML is used for "guessing" when user is vague.
    # If User was specific (Rule detected params), we use Rule.
    # If User was vague (Rule used defaults), we might trust ML?
    # For now, "Make existing parts impossible to fail" -> Rule Priority for explicit inputs.
    
    final_params = rule_params # Default to rules (supports units)

    # 3. Validate (Fail Fast)
    try:
        validate(final_params, intent)
    except ValueError as e:
         raise HTTPException(status_code=400, detail=str(e))

    # 4. Build Geometry (Registry Lookup)
    try:
        part_cls = PART_REGISTRY[intent.part_type]
        part = part_cls(final_params)
        model = part.build()
    except Exception as e:
        print(f"CRITICAL BUILD ERROR: {e}")
        raise HTTPException(status_code=400, detail=str(e))



    exporters.export(model, str(step_path))
    exporters.export(model, str(stl_path))

    convert_stl_to_glb(stl_path, glb_path)

    # Convert simple params to a faux-feature-graph structure for frontend compatibility
    # The frontend likely expects: { features: [...], part_type: ... }
    # We will mock it so the frontend doesn't crash, but regenerate might be limited until updated.
    
    # We construct a single feature representing the part
    mock_feature = {
        "type": intent.part_type,
        "params": final_params,
        "units": param_units,
        "name": "Main Shape",
        "id": str(uuid.uuid4())
    }
    
    feature_graph_dict = {
        "part_type": intent.part_type,
        "features": [mock_feature]
    }

    return {
        "job_id": job_id,
        "prompt": request.prompt,
        "prompt": request.prompt,
        "parameters": final_params,
        "feature_graph": feature_graph_dict, 
        "ml_deviation_check": {
            "rules": rule_params,
            "ml": ml_params
        },
        "files": {
            "step": str(step_path),
            "stl": str(stl_path),
            "glb": str(glb_path)
        }
    }


@app.post("/regenerate")
def regenerate_cad(request: RegenerateRequest):
    """
    Regenerate CAD from an edited Feature Graph (Graph -> Geometry)
    """
    job_id = str(uuid.uuid4())

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    step_path = output_dir / f"{job_id}.step"
    stl_path = output_dir / f"{job_id}.stl"
    glb_path = output_dir / f"{job_id}.glb"

    # 1. Rehydrate Graph
    try:
        graph = FeatureGraph(**request.feature_graph)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Graph: {e}")
    
    # 2. Rebuild Geometry (Enforces constraints & sorts internally)
    try:
        model = build_from_graph(graph)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Build Error: {e}")

    # 3. Export
    exporters.export(model, str(step_path))
    exporters.export(model, str(stl_path))
    
    convert_stl_to_glb(stl_path, glb_path)
    
    # 4. Active Learning: Log Feedback
    flattened_params = {}
    for f in graph.features:
        flattened_params.update(f.params)
        
    log_feedback(request.prompt, flattened_params, graph.part_type)

    return {
        "job_id": job_id,
        "feature_graph": graph.model_dump(),
        "files": {
            "step": str(step_path),
            "stl": str(stl_path),
            "glb": str(glb_path)
        }
    }

@app.post("/describe")
def describe_cad(request: DescribeRequest):
    """
    Describe the Feature Graph in plain text.
    """
    try:
        graph = FeatureGraph(**request.feature_graph)
        description = describe_feature_graph(graph)
        return {"description": description}
    except Exception as e:
         raise HTTPException(status_code=400, detail=str(e))

@app.get("/download/step/{filename}")
def download_step(filename: str):
    """
    Force download of STEP file.
    """
    file_path = Path("outputs") / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        media_type="application/step", # or "application/octet-stream"
        filename=filename, # Triggers browser download
    )

from app.routers import generation_v2
app.include_router(generation_v2.router)

