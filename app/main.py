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
from app.ml.predictor_xgb import infer_parameters_xgb as infer_parameters
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

    # 1. Parse Intent (Locked)
    try:
        intent = parse_intent(request.prompt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    print(f"DEBUG: Intent={intent}")

    # 2. Infer Parameters (Context-Aware)
    raw_params, param_units = infer_parameters(intent, request.prompt)
    
    # 3. Validate (Fail Fast)
    try:
        validate(raw_params, intent)
    except ValueError as e:
         raise HTTPException(status_code=400, detail=str(e))
         
    print(f"DEBUG: Params={raw_params}")

    # 4. Build Geometry (Registry Lookup)
    try:
        part_cls = PART_REGISTRY[intent.part_type]
        
        # Stress Test (Advanced)
        # We run a quick check on tweaked params to ensure stability
        # stress_test(part_cls, raw_params) # Optional: enable if performant enough
        
        part = part_cls(raw_params)
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
        "params": raw_params,
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
        "parameters": raw_params,
        "feature_graph": feature_graph_dict, 
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

