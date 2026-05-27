"""
OrionFlow Studio FastAPI app.

Entry point is `studio.py` at the repo root which simply does
`uvicorn.run("studio_app.app:app", ...)`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from studio_app.exec_sandbox import execute_code
from studio_app.agentic import router as agentic_router


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
STUDIO_OUTPUT_DIR = ROOT / "outputs" / "studio"
STUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="OrionFlow Studio")
app.mount("/models", StaticFiles(directory=str(STUDIO_OUTPUT_DIR)), name="models")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(agentic_router)


class RunRequest(BaseModel):
    prompt: str = ""
    code: str


@app.post("/run")
def run(req: RunRequest):
    return JSONResponse(execute_code(req.code, STUDIO_OUTPUT_DIR))


@app.get("/health")
def health():
    return {"ok": True, "studio_dir": str(STUDIO_OUTPUT_DIR)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
