"""
OrionFlow CAD Engine - FastAPI Application Entry Point.

This module initializes the FastAPI application, configures middleware,
and defines REST API endpoints for CAD generation.

API Endpoints:
    POST /generate     - Generate CAD from natural language prompt
    POST /regenerate   - Regenerate CAD from edited feature graph
    POST /describe     - Describe feature graph in plain text
    GET  /download/step/{filename} - Download STEP file
    GET  /download/stl/{filename}  - Download STL file
    GET  /outputs/{filename}       - Serve generated files (static)
    GET  /health                   - Health check endpoint
    GET  /docs                     - OpenAPI documentation (Swagger UI)
    GET  /redoc                    - ReDoc documentation
"""
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Centralized Configuration
from app.config import settings

# Structured Logging
from app.logging_config import configure_logging, get_logger, set_request_id, generate_request_id

# Exception Handling
from app.exceptions import OrionFlowError, ValidationError, LLMError, CompilationError

# Service Layer
from app.services.generation_service import GenerationService

# Domain Models
from app.domain.feature_graph import FeatureGraph
from app.cad.describe import describe_feature_graph

# Configure structured logging
configure_logging()
logger = get_logger(__name__)


# =============================================================================
# Request/Response Models with OpenAPI Documentation
# =============================================================================

class GenerateRequest(BaseModel):
    """Request body for CAD generation from natural language."""
    
    prompt: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Natural language description of the CAD model to generate",
        json_schema_extra={
            "example": "Create a 20mm tall cylinder with 10mm radius"
        }
    )
    
    backend: Optional[str] = Field(
        default="build123d",
        description="CAD backend to use: 'build123d' (local) or 'onshape' (cloud)"
    )


class RegenerateRequest(BaseModel):
    """Request body for regenerating CAD from edited feature graph."""
    
    feature_graph: Dict = Field(
        ...,
        description="The edited FeatureGraph JSON structure"
    )
    
    prompt: str = Field(
        default="",
        description="Optional prompt context for feedback logging"
    )


class DescribeRequest(BaseModel):
    """Request body for describing a feature graph in plain text."""
    
    feature_graph: Dict = Field(
        ...,
        description="The FeatureGraph JSON to describe"
    )


class ViewerInfo(BaseModel):
    """3D viewer information."""
    glb_url: str = Field(..., description="URL to GLB file for 3D viewing")


class DownloadLinks(BaseModel):
    """Download links for CAD files."""
    step: str = Field(..., description="URL to STEP file (B-Rep for manufacturing)")
    stl: str = Field(..., description="URL to STL file (mesh for 3D printing)")


class GenerateResponse(BaseModel):
    """Response from CAD generation endpoint."""
    
    model_id: str = Field(..., description="Unique identifier for the generated model")
    viewer: ViewerInfo = Field(..., description="3D viewer information")
    downloads: DownloadLinks = Field(..., description="Download links for CAD files")
    cfg: Dict = Field(..., description="The generated FeatureGraph (CFG)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "model_id": "550e8400-e29b-41d4-a716-446655440000",
                "viewer": {"glb_url": "outputs/550e8400.glb"},
                "downloads": {
                    "step": "outputs/550e8400.step",
                    "stl": "outputs/550e8400.stl"
                },
                "cfg": {
                    "version": "v1",
                    "units": "mm",
                    "sketches": [],
                    "features": [],
                    "parameters": {"radius": 10.0, "height": 20.0}
                }
            }
        }
    }


class DescribeResponse(BaseModel):
    """Response from describe endpoint."""
    description: str = Field(..., description="Human-readable description of the CAD model")


class HealthResponse(BaseModel):
    """Response from health check endpoint."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    llm_configured: bool = Field(..., description="Whether LLM API is configured")
    onshape_configured: bool = Field(..., description="Whether Onshape integration is configured")


class ErrorResponse(BaseModel):
    """Standardized error response."""
    error: str = Field(..., description="Error message")
    code: str = Field(..., description="Error code")
    retryable: bool = Field(default=False, description="Whether the error is retryable")


# =============================================================================
# FastAPI Application Initialization
# =============================================================================

app = FastAPI(
    title="OrionFlow CAD Engine",
    description="""
## AI-Powered Text-to-CAD Generation API

OrionFlow converts natural language descriptions into parametric CAD models.

### Features
- **Natural Language Input**: Describe your part in plain English
- **Parametric Output**: Edit dimensions after generation
- **Multiple Formats**: Export to STEP, STL, and GLB
- **Cloud Sync**: Optional Onshape integration

### Quick Start
```bash
curl -X POST http://localhost:8000/generate \\
  -H "Content-Type: application/json" \\
  -d '{"prompt": "Create a 20mm cube"}'
```

### Supported Primitives
- Rectangle, Circle, Polygon profiles
- Extrude, Revolve operations
- Fillet, Chamfer features (coming soon)
    """,
    version="0.2.0",
    contact={
        "name": "OrionFlow Team",
        "url": "https://github.com/sahilmaniyar888/OrionFlow_CAD"
    },
    license_info={
        "name": "MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "Generation", "description": "CAD generation endpoints"},
        {"name": "Downloads", "description": "File download endpoints"},
        {"name": "Utilities", "description": "Utility endpoints"},
    ]
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Middleware: Request ID Tracking
# =============================================================================

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Add request ID to each request for tracing."""
    request_id = request.headers.get("X-Request-ID") or generate_request_id()
    set_request_id(request_id)
    
    logger.info(
        "request_started",
        method=request.method,
        path=request.url.path,
        request_id=request_id
    )
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        request_id=request_id
    )
    
    return response


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(OrionFlowError)
async def orionflow_exception_handler(request: Request, exc: OrionFlowError):
    """Handle all OrionFlow custom exceptions."""
    logger.error(
        "orionflow_error",
        error_code=exc.code.value,
        message=exc.message,
        retryable=exc.retryable,
        details=exc.details
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTP exceptions."""
    logger.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=str(exc.detail)
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "retryable": exc.status_code >= 500
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.exception(
        "unexpected_error",
        error_type=type(exc).__name__,
        message=str(exc)
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Please try again.",
                "retryable": True
            }
        }
    )


# Mount static files for output serving
settings.output_dir.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(settings.output_dir)), name="outputs")

# Initialize Generation Service with configuration
generation_service = GenerationService(
    output_dir=settings.output_dir,
    use_v3_compiler=settings.use_v3_compiler,
    use_two_stage=settings.use_two_stage_pipeline
)

# Log startup configuration
if settings.debug:
    settings.print_config_summary()


# =============================================================================
# API Endpoints
# =============================================================================

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Utilities"],
    summary="Health check endpoint"
)
async def health_check():
    """
    Check service health and configuration status.
    
    Returns current API version and configuration state.
    """
    return HealthResponse(
        status="healthy",
        version="0.2.0",
        llm_configured=settings.has_llm_api_key,
        onshape_configured=settings.is_onshape_configured
    )


@app.post(
    "/generate",
    response_model=GenerateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Generation failed"}
    },
    tags=["Generation"],
    summary="Generate CAD from natural language"
)
async def generate_cad(request: GenerateRequest):
    """
    Generate a parametric CAD model from natural language prompt.
    
    This endpoint uses LLM to interpret the prompt and generate a FeatureGraph,
    which is then compiled to geometry (STEP, STL, GLB files).
    
    **Example prompts:**
    - "Create a 20mm tall cylinder with 10mm radius"
    - "Make a rectangular plate 50mm x 30mm x 5mm thick"
    - "Design a box with rounded corners"
    
    **Response includes:**
    - `model_id`: Unique identifier for the generated model
    - `viewer.glb_url`: URL to GLB file for 3D preview
    - `downloads`: Links to STEP and STL files
    - `cfg`: The generated FeatureGraph (editable parameters)
    """
    logger.info(f"Generate request: prompt='{request.prompt[:50]}...'")
    
    try:
        result = await generation_service.generate(
            request.prompt, 
            backend=request.backend
        )
    except ValueError as e:
        logger.warning(f"Generation validation error: {e}")
        raise HTTPException(
            status_code=400, 
            detail={"error": str(e), "code": "VALIDATION_ERROR", "retryable": False}
        )
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(
            status_code=500, 
            detail={"error": str(e), "code": "GENERATION_FAILED", "retryable": True}
        )
    
    # Build response
    fg_data = result.metadata.get("feature_graph", {})
    if "parameters" not in fg_data and "parameters" in result.metadata:
        fg_data["parameters"] = result.metadata["parameters"]

    return GenerateResponse(
        model_id=result.metadata["job_id"],
        viewer=ViewerInfo(
            glb_url=str(result.geometry_path).replace("\\", "/")
        ),
        downloads=DownloadLinks(
            step=str(result.metadata.get("step_path", "")).replace("\\", "/"),
            stl=str(result.metadata.get("stl_path", "")).replace("\\", "/")
        ),
        cfg=fg_data
    )


@app.post(
    "/regenerate",
    response_model=GenerateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid feature graph"}
    },
    tags=["Generation"],
    summary="Regenerate CAD from edited feature graph"
)
async def regenerate_cad(request: RegenerateRequest):
    """
    Regenerate CAD geometry from an edited FeatureGraph.
    
    Use this endpoint after modifying parameters in the `cfg` object
    returned from `/generate`. This enables parametric editing without
    re-invoking the LLM.
    
    **Workflow:**
    1. Call `/generate` to create initial model
    2. Modify `cfg.parameters` (e.g., increase `height` from 20 to 30)
    3. Call `/regenerate` with modified `cfg`
    4. Receive new geometry files
    
    **Supports conversational edits:**
    - Include `prompt` to apply natural language edits
    - Example: `{"prompt": "make it taller", "feature_graph": {...}}`
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
            logger.info(f"Applied conversational edit: '{request.prompt}'")
        
        # Regenerate geometry
        result = await generation_service.regenerate(
            feature_graph.model_dump(), 
            request.prompt
        )
        
    except Exception as e:
        logger.error(f"Regeneration failed: {e}")
        raise HTTPException(
            status_code=400, 
            detail={"error": str(e), "code": "REGENERATION_FAILED", "retryable": False}
        )
    
    return GenerateResponse(
        model_id=result.metadata["job_id"],
        viewer=ViewerInfo(
            glb_url=str(result.geometry_path).replace("\\", "/")
        ),
        downloads=DownloadLinks(
            step=str(result.metadata["step_path"]).replace("\\", "/"),
            stl=str(result.metadata["stl_path"]).replace("\\", "/")
        ),
        cfg=result.metadata["feature_graph"]
    )


@app.post(
    "/describe",
    response_model=DescribeResponse,
    tags=["Utilities"],
    summary="Describe feature graph in plain text"
)
def describe_cad(request: DescribeRequest):
    """
    Convert a FeatureGraph to human-readable description.
    
    Useful for:
    - Generating documentation
    - Accessibility features
    - Debugging CAD structures
    """
    try:
        graph = FeatureGraph(**request.feature_graph)
        description = describe_feature_graph(graph)
        return DescribeResponse(description=description)
    except Exception as e:
        logger.error(f"Describe failed: {e}")
        raise HTTPException(
            status_code=400, 
            detail={"error": str(e), "code": "DESCRIBE_FAILED", "retryable": False}
        )


@app.get(
    "/download/step/{filename}",
    tags=["Downloads"],
    summary="Download STEP file"
)
def download_step(filename: str):
    """
    Download a STEP file by filename.
    
    STEP files contain exact B-Rep geometry suitable for:
    - CNC machining
    - Professional CAD software import
    - Manufacturing workflows
    """
    file_path = settings.output_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        media_type="application/step",
        filename=filename,
    )


@app.get(
    "/download/stl/{filename}",
    tags=["Downloads"],
    summary="Download STL file"
)
def download_stl(filename: str):
    """
    Download an STL file by filename.
    
    STL files contain tessellated mesh geometry suitable for:
    - 3D printing (FDM, SLA, SLS)
    - Rendering and visualization
    - Mesh processing
    """
    file_path = settings.output_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        media_type="application/sla",
        filename=filename,
    )


# =============================================================================
# Startup/Shutdown Events
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Log startup information."""
    logger.info("=" * 60)
    logger.info("OrionFlow CAD Engine Starting")
    logger.info("=" * 60)
    logger.info(f"API Version: 0.2.0")
    logger.info(f"Output Directory: {settings.output_dir}")
    logger.info(f"LLM Provider: {settings.llm_provider}")
    logger.info(f"LLM Configured: {settings.has_llm_api_key}")
    logger.info(f"Onshape Configured: {settings.is_onshape_configured}")
    logger.info(f"CORS Origins: {settings.cors_origins_list}")
    logger.info(f"Debug Mode: {settings.debug}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown."""
    logger.info("OrionFlow CAD Engine Shutting Down")
