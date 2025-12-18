import os
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, Body
from pydantic import BaseModel

import cadquery as cq
from cadquery import exporters

from dotenv import load_dotenv
from google import genai


# Load environment variables from .env
load_dotenv()

# Read Gemini API key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY not found in environment")

# Initialize Gemini client
client = genai.Client(api_key=api_key)



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


def gemini_extract_parameters(prompt: str) -> dict:
    """
    Uses Gemini Flash-3 to extract CAD parameters as STRICT JSON.
    """

    system_prompt = f"""
You are a mechanical CAD parameter extraction assistant.

TASK:
Extract numeric parameters from the user text.

RULES:
- Output ONLY valid JSON
- NO explanations
- NO markdown
- NO units
- ONLY these keys are allowed: {list(ALLOWED_PARAMETERS.keys())}
- If a parameter is not mentioned, omit it

EXAMPLE OUTPUT:
{{ "radius": 25, "height": 10 }}

USER TEXT:
{prompt}
"""

    response = client.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=system_prompt
    )

    text = response.text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Safety fallback
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

    raw_params = gemini_extract_parameters(request.prompt)
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


