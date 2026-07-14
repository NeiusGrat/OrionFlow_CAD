"""OFL API endpoints — generate, rebuild, edit, download."""

import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.domain.ofl_models import (
    OFLGenerateRequest,
    OFLRebuildRequest,
    OFLEditRequest,
    OFLGenerateResponse,
)
from app.services.ofl_telemetry import log_ofl_event

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
async def ofl_generate(
    request: OFLGenerateRequest,
    background: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    """Generate OFL code + STEP/STL/GLB from natural language prompt."""
    response = _get_generate_service().generate_from_prompt(request.prompt)
    background.add_task(
        log_ofl_event, "generate", response,
        prompt=request.prompt, authorization=authorization,
    )
    return response


@router.post("/rebuild", response_model=OFLGenerateResponse)
async def ofl_rebuild(
    request: OFLRebuildRequest,
    background: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    """Re-execute edited OFL code. No LLM call — instant rebuild."""
    response = _get_rebuild_service().rebuild_from_code(request.ofl_code)
    background.add_task(
        log_ofl_event, "rebuild", response,
        input_code=request.ofl_code, authorization=authorization,
    )
    return response


@router.post("/edit", response_model=OFLGenerateResponse)
async def ofl_edit(
    request: OFLEditRequest,
    background: BackgroundTasks,
    authorization: Optional[str] = Header(None),
):
    """Apply natural language edit to existing OFL code."""
    response = _get_generate_service().edit_from_instruction(
        request.ofl_code, request.edit_instruction
    )
    background.add_task(
        log_ofl_event, "edit", response,
        prompt=request.edit_instruction, input_code=request.ofl_code,
        authorization=authorization,
    )
    return response


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
        # Local dir is ephemeral; older artifacts only exist in object storage.
        from app.config import settings

        if settings.is_s3_configured:
            from app.services.storage import get_storage

            url = get_storage().url_for(f"ofl/{request_id}/{filename}")
            if url:
                return RedirectResponse(url=url, status_code=307)
        raise HTTPException(404, "File not found")

    media_types = {
        ".step": "application/STEP",
        ".stl": "application/sla",
        ".glb": "model/gltf-binary",
    }
    ext = os.path.splitext(filename)[1].lower()
    return FileResponse(
        filepath,
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=filename,
    )
