"""Pydantic models for OFL API endpoints."""

from pydantic import BaseModel, Field
from typing import Optional


class OFLGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=5, max_length=2000,
                        description="Natural language part description")


class OFLRebuildRequest(BaseModel):
    ofl_code: str = Field(..., description="Complete OFL Python code string")


class OFLEditRequest(BaseModel):
    ofl_code: str = Field(..., description="Current OFL code")
    edit_instruction: str = Field(..., description="e.g. 'change M5 holes to M6'")


class OFLFileLinks(BaseModel):
    step: Optional[str] = None
    stl: Optional[str] = None
    glb: Optional[str] = None


class OFLParameter(BaseModel):
    name: str
    value: float
    line_number: int


class OFLGenerateResponse(BaseModel):
    success: bool
    ofl_code: str = ""
    files: OFLFileLinks = OFLFileLinks()
    parameters: list[OFLParameter] = []
    error: Optional[str] = None
    generation_time_ms: float = 0
