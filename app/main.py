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
from app.domain.feature_graph import FeatureGraph
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
async def generate_cad(request: GenerateRequest):
    """
    Generate CAD from natural language prompt (Unified Pipeline)
    Uses the new canonical generate() method.
    """
    print(f"API REQUEST RECEIVED: {request.prompt}")
    try:
        result = await generation_service.generate(request.prompt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"CRITICAL BUILD ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    # Backward-compatible response format
    fg = result.metadata.get("feature_graph", {})
    return {
        "job_id": result.metadata["job_id"],
        "prompt": request.prompt,
        "parameters": fg.get("parameters", {}),
        "feature_graph": fg,
        "files": {
            "step": str(result.metadata.get("step_path", "")).replace("\\", "/"),
            "stl": str(result.metadata.get("stl_path", "")).replace("\\", "/"),
            "glb": str(result.geometry_path).replace("\\", "/")
        }
    }


@app.post("/regenerate")
async def regenerate_cad(request: RegenerateRequest):
    """
    Regenerate CAD from edited feature graph OR apply conversational edit.
    
    Supports:
    1. Direct graph editing (parametric CAD)
    2. Conversational edits ("make it taller")
    """
    from app.services.conversational_editor import ConversationalEditor
    from app.domain.feature_graph import FeatureGraph
    
    try:
        # Parse feature graph
        feature_graph = FeatureGraph(**request.feature_graph)
        
        # Apply conversational edit if prompted
        if request.prompt and request.prompt.strip():
            editor = ConversationalEditor()
            feature_graph = await editor.apply_edit(feature_graph, request.prompt)
            print(f"Applied edit: '{request.prompt}'")
        
        # Regenerate geometry
        result = await generation_service.regenerate(feature_graph.model_dump(), request.prompt)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {
        "job_id": result.metadata["job_id"],
        "feature_graph": result.metadata["feature_graph"],
        "files": {
            "step": str(result.metadata["step_path"]).replace("\\", "/"),
            "stl": str(result.metadata["stl_path"]).replace("\\", "/"),
            "glb": str(result.geometry_path).replace("\\", "/")
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

@app.get("/download/stl/{filename}")
def download_stl(filename: str):
    """
    Force download of STL file.
    """
    file_path = Path("outputs") / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        media_type="application/sla", # Common MIME for STL
        filename=filename,
    )


