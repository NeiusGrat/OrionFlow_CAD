from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse
import io

from app.agent.llm_client import LLMClient

router = APIRouter(
    prefix="/api/v2/export",
    tags=["v2-export"]
)

llm_client = LLMClient()

class ExportRequest(BaseModel):
    prompt: str

@router.post("/solidworks")
async def export_solidworks_macro(request: ExportRequest):
    """
    Generates a SolidWorks VBA macro for the given prompt and creates a file download.
    """
    try:
        print(f"Generating SW Macro for: {request.prompt}")
        macro_code = await llm_client.generate_solidworks_macro(request.prompt)
        
        # Convert string to bytes stream
        file_stream = io.BytesIO(macro_code.encode("utf-8"))
        
        return StreamingResponse(
            file_stream,
            media_type="text/plain", # Use text/plain for simplicity/compatibility
            headers={
                "Content-Disposition": 'attachment; filename="orion_macro.vba"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
