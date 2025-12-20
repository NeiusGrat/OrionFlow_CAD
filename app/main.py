import os
import json
import uuid
import datetime
from pathlib import Path

from fastapi import FastAPI, Body, HTTPException
from pydantic import BaseModel

import cadquery as cq
from cadquery import exporters

from dotenv import load_dotenv

import trimesh

from app.ml.predictor import predict_parameters
from app.ml.rules import infer_part_type
from app.cad.graph_builder import build_cylinder_graph, build_box_graph, build_shaft_graph
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

def sanitize_parameters(raw_params: dict) -> dict:
    """
    Enforces parameter bounds and defaults.
    """
    safe = {}
    # We relax the strict ALLOWED_PARAMETERS check for now to allow new params (length, width)
    # But we still want to ensure they are numeric.
    for k, v in raw_params.items():
        if isinstance(v, (int, float)):
            safe[k] = v
    return safe


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
    Generate a CAD model from text (Prompt -> ML -> Graph -> Geometry)
    Now supports Multiple Part Types!
    """
    job_id = str(uuid.uuid4())

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    step_path = output_dir / f"{job_id}.step"
    stl_path = output_dir / f"{job_id}.stl"
    glb_path = output_dir / f"{job_id}.glb"


    # 1. Infer Part Type & Predict
    part_type = infer_part_type(request.prompt)
    raw_params = predict_parameters(request.prompt)
    safe_params = sanitize_parameters(raw_params)

    # 2. Build Graph (Route to correct builder)
    if part_type == "box":
        graph = build_box_graph(safe_params)
    elif part_type == "shaft":
        graph = build_shaft_graph(safe_params)
    else:
        graph = build_cylinder_graph(safe_params)

    # 3. Build Geometry from Graph
    try:
        model = build_from_graph(graph)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


    exporters.export(model, str(step_path))
    exporters.export(model, str(stl_path))

    convert_stl_to_glb(stl_path, glb_path)


    return {
        "job_id": job_id,
        "prompt": request.prompt,
        "parameters": safe_params,
        "feature_graph": graph.model_dump(),
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
    # Extract flattened params from graph for simplified logging
    # (Assuming single feature params for now or we log full graph)
    # The prompt asked for "final_parameters". We can extract them from the graph logic.
    # For now logging the first feature params is often enough for simple parts, 
    # but let's aggregate all params.
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
