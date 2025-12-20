import os
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, Body
from pydantic import BaseModel

import cadquery as cq
from cadquery import exporters

from dotenv import load_dotenv

import trimesh

from app.ml.predictor import predict_parameters
from app.cad.graph_builder import build_cylinder_graph
from app.cad.cq_builder import build_from_graph
from app.cad.feature_graph import FeatureGraph

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
    

def sanitize_parameters(raw_params: dict) -> dict:
    """
    Enforces parameter bounds and defaults.
    """
    safe = {}
    for name, rules in ALLOWED_PARAMETERS.items():
        value = raw_params.get(name, rules["default"])
        value = max(rules["min"], min(rules["max"], value))
        safe[name] = value
    return safe


def convert_stl_to_glb(stl_path: Path, glb_path: Path):
    """
    Converts STL mesh to GLB for browser visualization.
    """
    mesh = trimesh.load_mesh(stl_path)
    glb_bytes = mesh.export(file_type="glb")
    glb_path.write_bytes(glb_bytes)



@app.post("/generate")
def generate_cad(request: GenerateRequest):
    """
    Generate a CAD model from text (Prompt -> ML -> Graph -> Geometry)
    """
    job_id = str(uuid.uuid4())

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    step_path = output_dir / f"{job_id}.step"
    stl_path = output_dir / f"{job_id}.stl"
    glb_path = output_dir / f"{job_id}.glb"


    # 1. Predict
    raw_params = predict_parameters(request.prompt)
    safe_params = sanitize_parameters(raw_params)

    # 2. Build Graph (The Source of Truth)
    graph = build_cylinder_graph(safe_params)

    # 3. Build Geometry from Graph
    model = build_from_graph(graph)


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
    graph = FeatureGraph(**request.feature_graph)
    
    # 2. Rebuild Geometry
    model = build_from_graph(graph)

    # 3. Export
    exporters.export(model, str(step_path))
    exporters.export(model, str(stl_path))
    
    convert_stl_to_glb(stl_path, glb_path)

    return {
        "job_id": job_id,
        "feature_graph": graph.model_dump(),
        "files": {
            "step": str(step_path),
            "stl": str(stl_path),
            "glb": str(glb_path)
        }
    }
