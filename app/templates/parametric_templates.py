"""
Parametric Templates - Phase 4 Stage 2

Template-based FeatureGraph generation from DesignIntent.

Templates are pre-validated, engineering-grade blueprints that the LLM
fills with parameters instead of hallucinating topology.

Benefits:
- Zero topology hallucinations
- Manufacturing-ready by default
- Consistent quality
- Faster generation (simpler LLM task)
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from pathlib import Path

from app.domain.feature_graph_v3 import FeatureGraphV3, FeatureV2, SketchGraphV2, SketchPrimitiveV2, Constraint, ConstraintType
from app.domain.design_intent import DesignIntent, ManufacturingProcess
from app.domain.feature_graph_v2 import SemanticSelector, SelectorType


class ParametricTemplate(ABC):
    """
    Base class for design templates.
    
    Each template represents a common mechanical part with
    validated topology and configurable parameters.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Template name for registry."""
        pass
    
    @abstractmethod
    def generate(self, intent: DesignIntent) -> FeatureGraphV3:
        """
        Generate FeatureGraph from design intent.
        
        Args:
            intent: Validated DesignIntent with key_dimensions
            
        Returns:
            Complete, validated FeatureGraphV3
        """
        pass
    
    @abstractmethod
    def required_dimensions(self) -> List[str]:
        """List of required key_dimensions for this template."""
        pass
    
    def validate_intent(self, intent: DesignIntent) -> bool:
        """Check if intent has all required dimensions."""
        return all(dim in intent.key_dimensions for dim in self.required_dimensions())


class BoxTemplate(ParametricTemplate):
    """
    Simple rectangular box/enclosure.
    
    Use cases:
    - Enclosures
    - Housings
    - Simple containers
    
    Parameters:
    - width: X dimension
    - depth: Y dimension
    - height: Z dimension (extrude)
    - wall_thickness: For shells (optional)
    """
    
    @property
    def name(self) -> str:
        return "BoxTemplate"
    
    def required_dimensions(self) -> List[str]:
        return ["width", "depth", "height"]
    
    def generate(self, intent: DesignIntent) -> FeatureGraphV3:
        """Generate box FeatureGraph."""
        
        # Extract dimensions
        width = intent.key_dimensions["width"]
        depth = intent.key_dimensions["depth"]
        height = intent.key_dimensions["height"]
        wall_thickness = intent.key_dimensions.get("wall_thickness", None)
        fillet_radius = intent.key_dimensions.get("fillet_radius", min(width, depth, height) * 0.05)
        
        # Clamp fillet to safe value
        max_fillet = min(width, depth, height) * 0.2
        fillet_radius = min(fillet_radius, max_fillet)
        
        graph = FeatureGraphV3(
            version="3.0",
            units="mm",
            metadata={
                "template": self.name,
                "intent": intent.model_dump()
            },
            parameters={
                "width": width,
                "depth": depth,
                "height": height,
                "fillet_radius": fillet_radius
            },
            sketches=[
                SketchGraphV2(
                    id="base_sketch",
                    plane="XY",
                    primitives=[
                        SketchPrimitiveV2(
                            id="base_rect",
                            type="rectangle",
                            params={"width": "$width", "height": "$depth"}
                        )
                    ],
                    constraints=[]
                )
            ],
            features=[
                FeatureV2(
                    id="extrude_body",
                    type="extrude",
                    sketch="base_sketch",
                    params={"depth": "$height"},
                    dependencies=[]
                ),
                FeatureV2(
                    id="fillet_edges",
                    type="fillet",
                    params={"radius": "$fillet_radius"},
                    topology_refs={
                        "edges": SemanticSelector(
                            selector_type=SelectorType.STRING,
                            string_selector=">Z",  # Top edges
                            description="Top edges for safety fillet"
                        )
                    },
                    dependencies=["extrude_body"]
                )
            ],
            constraints=[]
        )
        
        # Add shell if wall_thickness specified
        if wall_thickness:
            graph.parameters["wall_thickness"] = wall_thickness
            graph.features.append(
                FeatureV2(
                    id="shell_hollow",
                    type="shell",
                    params={"thickness": "$wall_thickness"},
                    topology_refs={
                        "faces": SemanticSelector(
                            selector_type=SelectorType.STRING,
                            string_selector=">Z",
                            description="Remove top face for shell"
                        )
                    },
                    dependencies=["fillet_edges"]
                )
            )
        
        return graph


class BracketTemplate(ParametricTemplate):
    """
    L-bracket with mounting holes.
    
    Use cases:
    - Motor mounts
    - Sensor brackets
    - Structural supports
    
    Parameters:
    - base_width: Horizontal leg width
    - vertical_height: Vertical leg height
    - thickness: Material thickness
    - hole_diameter: Mounting hole size (default: 5mm)
    - hole_count: Number of holes per leg (default: 2)
    """
    
    @property
    def name(self) -> str:
        return "BracketTemplate"
    
    def required_dimensions(self) -> List[str]:
        return ["base_width", "vertical_height", "thickness"]
    
    def generate(self, intent: DesignIntent) -> FeatureGraphV3:
        """Generate L-bracket FeatureGraph."""
        
        # Extract dimensions
        base_width = intent.key_dimensions["base_width"]
        vertical_height = intent.key_dimensions["vertical_height"]
        thickness = intent.key_dimensions["thickness"]
        hole_diameter = intent.key_dimensions.get("hole_diameter", 5.0)
        fillet_radius = intent.key_dimensions.get("fillet_radius", min(thickness * 0.3, 3.0))
        
        # Manufacturing constraint: fillet must be CNC-friendly
        min_fillet = 1.5  # Common 3mm tool
        fillet_radius = max(fillet_radius, min_fillet)
        
        graph = FeatureGraphV3(
            version="3.0",
            units="mm",
            metadata={
                "template": self.name,
                "intent": intent.model_dump(),
                "manufacturing_process": intent.manufacturing_process
            },
            parameters={
                "base_width": base_width,
                "vertical_height": vertical_height,
                "thickness": thickness,
                "hole_diameter": hole_diameter,
                "fillet_radius": fillet_radius
            },
            sketches=[
                # L-shaped profile sketch
                # Simplified: actual implementation would build L-shape from lines
                SketchGraphV2(
                    id="l_profile",
                    plane="XY",
                    primitives=[
                        # This is a simplification - real L-shape needs line primitives
                        # For now, use rectangle as placeholder
                        SketchPrimitiveV2(
                            id="base_leg",
                            type="rectangle",
                            params={"width": "$base_width", "height": "$thickness"}
                        )
                    ],
                    constraints=[]
                )
            ],
            features=[
                FeatureV2(
                    id="extrude_bracket",
                    type="extrude",
                    sketch="l_profile",
                    params={"depth": "$thickness"},
                    dependencies=[]
                ),
                FeatureV2(
                    id="fillet_corner",
                    type="fillet",
                    params={"radius": "$fillet_radius"},
                    topology_refs={
                        "edges": SemanticSelector(
                            selector_type=SelectorType.STRING,
                            string_selector="|Z",  # Vertical edges
                            description="Internal corner fillet"
                        )
                    },
                    dependencies=["extrude_bracket"]
                )
            ],
            constraints=[]
        )
        
        return graph


class PlateWithHolesTemplate(ParametricTemplate):
    """
    Flat plate with mounting holes.
    
    Use cases:
    - Mounting plates
    - Base plates
    - Interface adapters
    
    Parameters:
    - width, depth, thickness
    - hole_diameter
    - hole_pattern: "4_corner" or "grid"
    """
    
    @property
    def name(self) -> str:
        return "PlateWithHolesTemplate"
    
    def required_dimensions(self) -> List[str]:
        return ["width", "depth", "thickness"]
    
    def generate(self, intent: DesignIntent) -> FeatureGraphV3:
        """Generate plate with holes."""
        
        width = intent.key_dimensions["width"]
        depth = intent.key_dimensions["depth"]
        thickness = intent.key_dimensions["thickness"]
        hole_diameter = intent.key_dimensions.get("hole_diameter", 5.0)
        
        # Simple plate for now
        # TODO: Add hole pattern logic
        graph = FeatureGraphV3(
            version="3.0",
            units="mm",
            metadata={"template": self.name},
            parameters={
                "width": width,
                "depth": depth,
                "thickness": thickness,
                "hole_diameter": hole_diameter
            },
            sketches=[
                SketchGraphV2(
                    id="plate_outline",
                    plane="XY",
                    primitives=[
                        SketchPrimitiveV2(
                            id="outline",
                            type="rectangle",
                            params={"width": "$width", "height": "$depth"}
                        )
                    ]
                )
            ],
            features=[
                FeatureV2(
                    id="extrude_plate",
                    type="extrude",
                    sketch="plate_outline",
                    params={"depth": "$thickness"}
                )
            ]
        )
        
        return graph


class ShaftTemplate(ParametricTemplate):
    """
    Cylindrical shaft with features.
    
    Use cases:
    - Axles
    - Spindles
    - Pins
    
    Parameters:
    - diameter
    - length
    - shoulder_diameter (optional)
    - thread_diameter (optional)
    """
    
    @property
    def name(self) -> str:
        return "ShaftTemplate"
    
    def required_dimensions(self) -> List[str]:
        return ["diameter", "length"]
    
    def generate(self, intent: DesignIntent) -> FeatureGraphV3:
        """Generate shaft FeatureGraph."""
        
        diameter = intent.key_dimensions["diameter"]
        length = intent.key_dimensions["length"]
        
        graph = FeatureGraphV3(
            version="3.0",
            units="mm",
            metadata={"template": self.name},
            parameters={
                "diameter": diameter,
                "length": length
            },
            sketches=[
                SketchGraphV2(
                    id="shaft_profile",
                    plane="XY",
                    primitives=[
                        SketchPrimitiveV2(
                            id="circle",
                            type="circle",
                            params={"radius": "$diameter", "center_x": 0, "center_y": 0}
                        )
                    ]
                )
            ],
            features=[
                FeatureV2(
                    id="extrude_shaft",
                    type="extrude",
                    sketch="shaft_profile",
                    params={"depth": "$length"}
                )
            ]
        )
        
        return graph


# Template Registry
class TemplateRegistry:
    """Central registry of available templates."""
    
    _templates = {
        "BoxTemplate": BoxTemplate(),
        "BracketTemplate": BracketTemplate(),
        "PlateWithHolesTemplate": PlateWithHolesTemplate(),
        "ShaftTemplate": ShaftTemplate()
    }
    
    @classmethod
    def get(cls, template_name: str) -> Optional[ParametricTemplate]:
        """Get template by name."""
        return cls._templates.get(template_name)
    
    @classmethod
    def list_templates(cls) -> List[str]:
        """List all available template names."""
        return list(cls._templates.keys())
    
    @classmethod
    def select_template(cls, intent: DesignIntent) -> Optional[ParametricTemplate]:
        """
        Auto-select template based on DesignIntent.
        
        Args:
            intent: DesignIntent with part_type
            
        Returns:
            Template instance or None if not found
        """
        template_name = intent.template_name()
        return cls.get(template_name)
