from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from starlette.responses import StreamingResponse
import io

from app.agent.llm_client import LLMClient
from app.cad.generation_engine import execute_build123d_script, Build123dExecutionError

router = APIRouter(
    prefix="/api/v2/generate",
    tags=["v2-generative"]
)

llm_client = LLMClient()

class GenerateRequestV2(BaseModel):
    prompt: str
    model_size: str = "fast" # Placeholder for future model selection

class TestShimRequest(BaseModel):
    code: str

@router.post("")
async def generate_cad_v2(request: GenerateRequestV2):
    """
    V2 Generative Endpoint: Prompt -> LLM -> Code -> GLB
    """
    print(f"V2 Generation Request: {request.prompt}")
    
    # 1. Generate Code via LLM
    try:
        script = await llm_client.generate_cad_script(request.prompt)
        print(f"Generated Script:\n{script}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM Generation Failed: {str(e)}")

    # 2. Execute Code & Get GLB
    try:
        glb_bytes = execute_build123d_script(script)
    except Build123dExecutionError as e:
        print(f"Execution Error: {e}")
        # Return the generated code in the error for debugging
        raise HTTPException(status_code=400, detail={
            "error": str(e),
            "generated_code": script,
            "traceback": e.traceback_str
        })
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

    # 3. Return as Stream
    return StreamingResponse(
        io.BytesIO(glb_bytes), 
        media_type="model/gltf-binary",
        headers={"Content-Disposition": "attachment; filename=generated.glb"}
    )

@router.post("/test_shim")
async def test_shim_v2(request: TestShimRequest):
    """
    Directly test the execution engine with raw code (Phase 1 Requirement)
    """
    try:
        glb_bytes = execute_build123d_script(request.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    return StreamingResponse(
        io.BytesIO(glb_bytes), 
        media_type="model/gltf-binary"
    )
