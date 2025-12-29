import os
import json
import uuid
import datetime
from pathlib import Path

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dotenv import load_dotenv

# Service Layer (New Architecture)
from app.services.generation_service import GenerationService

# Keep for describe endpoint
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

# Instantiate Generation Service
generation_service = GenerationService(output_dir=Path("outputs"))


class GenerateRequest(BaseModel):
    prompt: str

class RegenerateRequest(BaseModel):
    feature_graph: dict
    prompt: str = "" # Optional prompt context for feedback logging

class DescribeRequest(BaseModel):
    feature_graph: dict



@app.post("/generate")
def generate_cad(request: GenerateRequest):
    """
    Generate a CAD model from text (V1 Pipeline: Prompt → Intent → Params → Geometry)
    Now uses GenerationService for better separation of concerns.
    """
    try:
        result, debug_info = generation_service.generate_v1(request.prompt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"CRITICAL BUILD ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    # Backward-compatible response format
    return {
        "job_id": result.metadata["job_id"],
        "prompt": request.prompt,
        "parameters": result.metadata["parameters"],
        "feature_graph": debug_info["feature_graph"],
        "ml_deviation_check": result.metadata["ml_deviation"],
        "files": {
            "step": str(debug_info["step_path"]),
            "stl": str(debug_info["stl_path"]),
            "glb": str(result.geometry_path)
        }
    }


@app.post("/regenerate")
def regenerate_cad(request: RegenerateRequest):
    """
    Regenerate CAD from an edited Feature Graph (Graph → Geometry)
    Now uses GenerationService for better separation of concerns.
    """
    try:
        result = generation_service.regenerate(request.feature_graph, request.prompt)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {
        "job_id": result.metadata["job_id"],
        "feature_graph": result.metadata["feature_graph"],
        "files": {
            "step": result.metadata["step_path"],
            "stl": result.metadata["stl_path"],
            "glb": str(result.geometry_path)
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

from app.routers import generation_v2, export
app.include_router(generation_v2.router)
app.include_router(export.router)

