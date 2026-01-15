"""
Design Intent Schema - Phase 4

High-level design reasoning without topology details.
Separates "what to build" from "how to build it."

Stage 1 of two-stage LLM pipeline:
1. LLM extracts DesignIntent from prompt (this file)
2. Template fills FeatureGraph from intent (templates.py)

Benefits:
- Eliminates topology hallucinations
- Focuses LLM on engineering reasoning
- Enables template-based generation
"""
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum


class PartType(str, Enum):
    """Common mechanical part categories."""
    BOX = "box"
    BRACKET = "bracket"
    PLATE = "plate"
    SHAFT = "shaft"
    CUSTOM = "custom"


class ManufacturingProcess(str, Enum):
    """Manufacturing processes with different constraints."""
    CNC_MILLING = "CNC"
    THREE_D_PRINT = "3D_print"
    CASTING = "casting"
    SHEET_METAL = "sheet_metal"
    INJECTION_MOLDING = "injection_molding"


class LoadAxis(str, Enum):
    """Primary load direction for structural analysis."""
    X = "X"
    Y = "Y"
    Z = "Z"
    RADIAL = "radial"  # For shafts
    NONE = "none"


class DesignIntent(BaseModel):
    """
    High-level design intent extracted from user prompt.
    
    This is what the LLM outputs in Stage 1, NOT a FeatureGraph.
    Stage 2 uses this to select and fill a template.
    
    Example:
        User: "Motor mount bracket for NEMA 23 stepper"
        
        DesignIntent:
            part_type: "bracket"
            manufacturing_process: "CNC"
            symmetry: True
            primary_load_axis: "Z"
            functional_requirements: ["mounting", "vibration_resistance"]
            key_dimensions: {"motor_width": 56, "thickness": 10}
    """
    # Core classification
    part_type: PartType = Field(..., description="Category of mechanical part")
    manufacturing_process: ManufacturingProcess = Field(
        default=ManufacturingProcess.CNC_MILLING,
        description="Target manufacturing method"
    )
    
    # Design characteristics
    symmetry: bool = Field(default=False, description="Is part symmetric about an axis?")
    primary_load_axis: Optional[LoadAxis] = Field(
        None,
        description="Main direction of force/load"
    )
    
    # Functional requirements
    functional_requirements: List[str] = Field(
        default_factory=list,
        description="What the part needs to do: mounting, clearance, support, etc."
    )
    
    # Key dimensions (template-specific)
    key_dimensions: Dict[str, float] = Field(
        default_factory=dict,
        description="Critical dimensions in mm: overall_length, width, thickness, hole_diameter, etc."
    )
    
    # Material hints (future)
    material_preference: Optional[str] = Field(
        None,
        description="Material suggestion: aluminum, steel, plastic"
    )
    
    # User's original prompt (for context)
    original_prompt: str = Field(default="", description="Original user request")
    
    class Config:
        use_enum_values = True
    
    def template_name(self) -> str:
        """
        Determine which template to use based on intent.
        
        Returns:
            Template class name (e.g., "BracketTemplate")
        """
        template_map = {
            PartType.BOX: "BoxTemplate",
            PartType.BRACKET: "BracketTemplate",
            PartType.PLATE: "PlateWithHolesTemplate",
            PartType.SHAFT: "ShaftTemplate",
            PartType.CUSTOM: "CustomTemplate"
        }
        return template_map.get(self.part_type, "BoxTemplate")
    
    def validate_for_template(self) -> List[str]:
        """
        Check if intent has required dimensions for selected template.
        
        Returns:
            List of missing dimensions (empty if valid)
        """
        required = {
            PartType.BOX: ["width", "depth", "height"],
            PartType.BRACKET: ["base_width", "vertical_height", "thickness"],
            PartType.PLATE: ["width", "depth", "thickness"],
            PartType.SHAFT: ["diameter", "length"]
        }
        
        needed_dims = required.get(self.part_type, [])
        missing = [d for d in needed_dims if d not in self.key_dimensions]
        
        return missing
