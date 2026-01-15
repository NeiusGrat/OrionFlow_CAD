"""
Manufacturing Intelligence - Phase 5

Production-ready constraint system for making designs manufacturable.

Key Features:
- Process-specific constraints (CNC, 3D print, casting)
- Tool diameter awareness
- Standard hole sizes
- Material thickness rules

Integration:
- Templates use constraints to set defaults
- Validators enforce constraints during compilation
- Errors suggest manufacturing-friendly fixes
"""
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from enum import Enum


class ManufacturingProcess(str, Enum):
    """Manufacturing processes with different design rules."""
    CNC_MILLING = "CNC"
    THREE_D_PRINT = "3D_print"
    CASTING = "casting"
    SHEET_METAL = "sheet_metal"
    INJECTION_MOLDING = "injection_molding"


class ManufacturingConstraints(BaseModel):
    """
    Process-specific manufacturing constraints.
    
    Applied during:
    1. Template generation (set safe defaults)
    2. Compiler validation (enforce rules)
    
    Example:
        CNC constraints:
        - min_fillet_radius = tool_diameter / 2
        - min_wall_thickness = 2mm
        - standard_hole_sizes = [3, 4, 5, 6, 8, 10]
    """
    process: ManufacturingProcess = Field(..., description="Manufacturing method")
    
    # Tool/Equipment constraints
    min_tool_diameter: Optional[float] = Field(
        None,
        description="Minimum tool diameter in mm (CNC)"
    )
    max_tool_length: Optional[float] = Field(
        None,
        description="Maximum tool reach in mm (CNC)"
    )
    
    # Geometry constraints
    min_fillet_radius: Optional[float] = Field(
        None,
        description="Minimum fillet radius in mm (computed from tool)"
    )
    min_wall_thickness: Optional[float] = Field(
        None,
        description="Minimum wall thickness in mm"
    )
    max_wall_thickness: Optional[float] = Field(
        None,
        description="Maximum wall thickness in mm (for uniform cooling in casting/injection)"
    )
    min_hole_diameter: Optional[float] = Field(
        None,
        description="Minimum drillable hole diameter in mm"
    )
    
    # Feature constraints
    max_aspect_ratio: Optional[float] = Field(
        None,
        description="Max depth:width ratio for pockets/slots"
    )
    draft_angle_required: Optional[float] = Field(
        None,
        description="Draft angle in degrees (casting/injection molding)"
    )
    support_overhang_angle: Optional[float] = Field(
        None,
        description="Max overhang angle without supports (3D printing)"
    )
    
    # Standards
    standard_hole_sizes: List[float] = Field(
        default_factory=list,
        description="Preferred hole diameters (ISO metric, ANSI inch, etc.)"
    )
    standard_thread_sizes: List[str] = Field(
        default_factory=list,
        description="Standard thread callouts: M3, M4, M5, 1/4-20, etc."
    )
    
    # Material properties (future)
    typical_materials: List[str] = Field(
        default_factory=list,
        description="Common materials for this process"
    )
    
    class Config:
        use_enum_values = True
    
    @classmethod
    def for_cnc_milling(cls, tool_diameter: float = 6.0) -> "ManufacturingConstraints":
        """
        Standard CNC milling constraints.
        
        Args:
            tool_diameter: Smallest end mill diameter in mm (default: 6mm)
            
        Returns:
            ManufacturingConstraints for CNC
        """
        return cls(
            process=ManufacturingProcess.CNC_MILLING,
            min_tool_diameter=tool_diameter,
            max_tool_length=100.0,  # Typical 4x diameter rule
            min_fillet_radius=tool_diameter / 2,  # Inside corners
            min_wall_thickness=2.0,
            min_hole_diameter=2.0,  # Smallest standard drill
            max_aspect_ratio=4.0,  # Depth:width for pockets
            standard_hole_sizes=[2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0],  # ISO metric
            standard_thread_sizes=["M3", "M4", "M5", "M6", "M8", "M10", "M12"],
            typical_materials=["Aluminum 6061", "Steel 1018", "Brass"]
        )
    
    @classmethod
    def for_3d_printing(cls, nozzle_diameter: float = 0.4) -> "ManufacturingConstraints":
        """
        Standard FDM 3D printing constraints.
        
        Args:
            nozzle_diameter: Nozzle size in mm (default: 0.4mm)
            
        Returns:
            ManufacturingConstraints for 3D printing
        """
        return cls(
            process=ManufacturingProcess.THREE_D_PRINT,
            min_wall_thickness=nozzle_diameter * 2,  # 2 perimeters minimum
            min_fillet_radius=0.5,  # Small radii print well
            support_overhang_angle=45.0,  # Max overhang without supports
            min_hole_diameter=1.0,  # Can print small holes
            standard_hole_sizes=[3.0, 4.0, 5.0],  # For tapping after print
            typical_materials=["PLA", "PETG", "ABS", "Nylon"]
        )
    
    @classmethod
    def for_casting(cls) -> "ManufacturingConstraints":
        """
        Standard sand casting constraints.
        
        Returns:
            ManufacturingConstraints for casting
        """
        return cls(
            process=ManufacturingProcess.CASTING,
            min_wall_thickness=4.0,  # Avoid shrinkage defects
            max_wall_thickness=25.0,  # Uniform cooling
            draft_angle_required=2.0,  # Degrees for mold release
            min_fillet_radius=3.0,  # Reduce stress concentrations
            typical_materials=["Aluminum A356", "Cast Iron", "Bronze"]
        )
    
    @classmethod
    def for_sheet_metal(cls, material_thickness: float = 1.5) -> "ManufacturingConstraints":
        """
        Standard sheet metal fabrication constraints.
        
        Args:
            material_thickness: Sheet thickness in mm
            
        Returns:
            ManufacturingConstraints for sheet metal
        """
        return cls(
            process=ManufacturingProcess.SHEET_METAL,
            min_fillet_radius=material_thickness,  # Bend radius = thickness minimum
            min_hole_diameter=material_thickness + 0.5,  # Hole edge distance rule
            typical_materials=["Steel sheet", "Aluminum sheet", "Stainless steel"]
        )


class MaterialSpec(BaseModel):
    """
    Material specification for design.
    
    Future: Integrate with FEA, cost estimation, etc.
    """
    name: str = Field(..., description="Material name: Aluminum 6061, PLA, etc.")
    density: Optional[float] = Field(None, description="Density in g/cm³")
    tensile_strength: Optional[float] = Field(None, description="Tensile strength in MPa")
    cost_per_kg: Optional[float] = Field(None, description="Material cost in $/kg")
    
    @classmethod
    def aluminum_6061(cls) -> "MaterialSpec":
        return cls(
            name="Aluminum 6061-T6",
            density=2.7,
            tensile_strength=310,
            cost_per_kg=5.0
        )
    
    @classmethod
    def pla(cls) -> "MaterialSpec":
        return cls(
            name="PLA (Polylactic Acid)",
            density=1.25,
            tensile_strength=50,
            cost_per_kg=25.0
        )
    
    @classmethod
    def steel_1018(cls) -> "MaterialSpec":
        return cls(
            name="Steel 1018",
            density=7.87,
            tensile_strength=440,
            cost_per_kg=2.0
        )
