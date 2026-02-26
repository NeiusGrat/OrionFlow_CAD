"""OFL API endpoints — generate, rebuild, edit, download."""

import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.domain.ofl_models import (
    OFLGenerateRequest, OFLRebuildRequest, OFLEditRequest, OFLGenerateResponse,
)

router = APIRouter(tags=["OFL"])

# Lazy init so server starts even without GROQ_API_KEY
_generate_service = None
_rebuild_service = None


def _get_generate_service():
    global _generate_service
    if _generate_service is None:
        from app.services.ofl_generation_service import OFLGenerationService
        _generate_service = OFLGenerationService(require_llm=True)
    return _generate_service


def _get_rebuild_service():
    """Rebuild service works without LLM / API key."""
    global _rebuild_service
    if _rebuild_service is None:
        from app.services.ofl_generation_service import OFLGenerationService
        _rebuild_service = OFLGenerationService(require_llm=False)
    return _rebuild_service


@router.post("/generate", response_model=OFLGenerateResponse)
async def ofl_generate(request: OFLGenerateRequest):
    """Generate OFL code + STEP/STL/GLB from natural language prompt."""
    return _get_generate_service().generate_from_prompt(request.prompt)


@router.post("/rebuild", response_model=OFLGenerateResponse)
async def ofl_rebuild(request: OFLRebuildRequest):
    """Re-execute edited OFL code. No LLM call — instant rebuild."""
    return _get_rebuild_service().rebuild_from_code(request.ofl_code)


@router.post("/edit", response_model=OFLGenerateResponse)
async def ofl_edit(request: OFLEditRequest):
    """Apply natural language edit to existing OFL code."""
    return _get_generate_service().edit_from_instruction(request.ofl_code, request.edit_instruction)


@router.get("/download/{request_id}/{filename}")
async def ofl_download(request_id: str, filename: str):
    """Download generated STEP/STL/GLB files."""
    if not request_id.isalnum() or len(request_id) != 12:
        raise HTTPException(400, "Invalid request ID")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")

    from app.services.ofl_sandbox import OUTPUT_BASE
    filepath = os.path.join(OUTPUT_BASE, request_id, filename)

    if not os.path.exists(filepath):
        raise HTTPException(404, "File not found")

    media_types = {
        ".step": "application/STEP",
        ".stl": "application/sla",
        ".glb": "model/gltf-binary",
    }
    ext = os.path.splitext(filename)[1].lower()
    return FileResponse(filepath, media_type=media_types.get(ext, "application/octet-stream"), filename=filename)
