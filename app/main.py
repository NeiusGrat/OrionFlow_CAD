from pydantic import BaseModel
from fastapi import FastAPI
import cadquery as cq
from cadquery import exporters
from pathlib import Path
import uuid


import os
from dotenv import load_dotenv
from google import genai

# 1. Load the variables from .env into the system environment
load_dotenv()

# 2. Retrieve the key securely
# We use os.getenv so that if the key is missing, the app doesn't crash immediately 
# but gives us a chance to handle the error.
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("No API Key found. Did you create the .env file?")

# 3. Initialize the client
client = genai.Client(api_key=api_key)

# Now you can use 'client' to generate content



ALLOWED_PARAMETERS = {
    "radius": {"min": 1, "max": 200, "default": 20},
    "height": {"min": 1, "max": 300, "default": 10}
}




app = FastAPI(
    title="OrionFlow CAD Engine",
    description="Text-to-Parametric CAD backend",
    version="0.1.0"
)

class GenerateRequest(BaseModel):
    prompt: str
    

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


def mock_llm_extract_parameters(prompt: str) -> dict:
    """
    Temporary stand-in for LLM.
    """
    if "large" in prompt.lower():
        return {"radius": 50, "height": 30}
    if "small" in prompt.lower():
        return {"radius": 10, "height": 5}
    return {}


def make_model(params: dict):
    radius = params["radius"]
    height = params["height"]

    return (
        cq.Workplane("XY")
        .circle(radius)
        .extrude(height)
    )




@app.post("/generate")
def generate_cad(request: GenerateRequest):
    """
    Generate a CAD model and export STEP + STL.
    """
    # EVERYTHING BELOW MUST BE INDENTED
    job_id = str(uuid.uuid4())

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    step_path = output_dir / f"{job_id}.step"
    stl_path = output_dir / f"{job_id}.stl"

    raw_params = mock_llm_extract_parameters(request.prompt)
    safe_params = sanitize_parameters(raw_params)
    model = make_model(safe_params)


    exporters.export(model, str(step_path)) # Better to cast Path to str for exporters
    exporters.export(model, str(stl_path))

    return {
        "job_id": job_id,
        "prompt": request.prompt,
        "parameters": safe_params,
        "files": {
            "step": str(step_path),
            "stl": str(stl_path)
        }
    }

