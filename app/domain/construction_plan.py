"""
Construction Plan Schema - Intermediate Planning Layer

Non-executable, reasoned CAD intent representation.
Lives between DecomposedIntent and FeatureGraph in the pipeline.

Pipeline Position:
  Text → DecomposedIntent → ConstructionPlan (this) → FeatureGraph → Compiler

Benefits:
- Enables rejection of bad plans before geometry generation
- Captures assumptions and open questions for clarification
- Improves LLM accuracy through structured reasoning
- Supports VLM + RL alignment for future enhancements
"""
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class PlanParameter(BaseModel):
    """
    A parameter in the construction plan with unit and dependency info.
    
    Example:
        PlanParameter(unit="mm", default=50.0, depends_on=None)
        PlanParameter(unit="mm", default=5.0, depends_on="height")
    """
    unit: Literal["mm", "inch", "deg", "rad"] = Field("mm", description="Unit of measurement")
    default: float = Field(..., description="Default value for this parameter")
    depends_on: Optional[str] = Field(None, description="Name of parameter this depends on (if any)")
    min_value: Optional[float] = Field(None, description="Minimum allowed value")
    max_value: Optional[float] = Field(None, description="Maximum allowed value")
    
    @field_validator('default')
    @classmethod
    def validate_default_positive(cls, v):
        """Most CAD parameters should be positive."""
        if v < 0:
            raise ValueError(f"Parameter default must be non-negative, got {v}")
        return v


class ConstructionPlan(BaseModel):
    """
    Non-executable representation of reasoned CAD intent.
    
    This layer captures the "what" and "why" of a design before
    committing to specific geometry. It enables:
    
    1. Plan validation before compilation
    2. User clarification requests for open questions
    3. Rejection of ambiguous or unsupported plans
    4. Better LLM alignment through explicit reasoning
    
    Example:
        ConstructionPlan(
            base_reference="XY plane",
            construction_sequence=[
                "Create base sketch: rectangle",
                "Extrude symmetrically",
                "Apply fillet only on top edges"
            ],
            parameters={
                "length": PlanParameter(unit="mm", default=50),
                "fillet_radius": PlanParameter(depends_on="height")
            },
            assumptions=["Sharp edges allowed on bottom"],
            open_questions=[]
        )
    """
    # Reference plane/origin for the design
    base_reference: str = Field(
        "XY plane",
        description="Reference plane or origin for the construction (e.g., 'XY plane', 'origin')"
    )
    
    # Ordered construction steps (human-readable)
    construction_sequence: List[str] = Field(
        ...,
        description="Ordered list of construction steps in plain language",
        min_length=1
    )
    
    # Parametric values with units and dependencies
    parameters: Dict[str, PlanParameter] = Field(
        default_factory=dict,
        description="Named parameters with units, defaults, and dependencies"
    )
    
    # Design assumptions made by the planner
    assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions made during planning (e.g., 'Sharp edges allowed on bottom')"
    )
    
    # Questions that need user clarification
    open_questions: List[str] = Field(
        default_factory=list,
        description="Questions requiring user input before proceeding"
    )
    
    # Optional metadata
    manufacturing_constraints: List[str] = Field(
        default_factory=list,
        description="Manufacturing constraints to consider (e.g., 'minimum wall thickness 2mm')"
    )
    
    design_rationale: Optional[str] = Field(
        None,
        description="Brief explanation of design choices"
    )

    def has_open_questions(self) -> bool:
        """Check if the plan has unresolved questions requiring user input."""
        return len(self.open_questions) > 0
    
    def validate_plan(self) -> List[str]:
        """
        Validate the construction plan for completeness and consistency.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check for empty construction sequence
        if not self.construction_sequence:
            errors.append("Construction sequence cannot be empty")
        
        # Check for parameter dependency cycles (simple check)
        for name, param in self.parameters.items():
            if param.depends_on:
                if param.depends_on == name:
                    errors.append(f"Parameter '{name}' has circular dependency (depends on itself)")
                elif param.depends_on not in self.parameters:
                    errors.append(f"Parameter '{name}' depends on unknown parameter '{param.depends_on}'")
        
        # Check for min/max validity
        for name, param in self.parameters.items():
            if param.min_value is not None and param.max_value is not None:
                if param.min_value > param.max_value:
                    errors.append(f"Parameter '{name}' has invalid range (min > max)")
            if param.min_value is not None and param.default < param.min_value:
                errors.append(f"Parameter '{name}' default is below minimum")
            if param.max_value is not None and param.default > param.max_value:
                errors.append(f"Parameter '{name}' default is above maximum")
        
        return errors
    
    def is_valid(self) -> bool:
        """Check if the plan passes all validation checks."""
        return len(self.validate_plan()) == 0
    
    def to_prompt_context(self) -> str:
        """
        Convert the plan to a prompt context string for LLM Stage 2.
        
        Returns:
            Formatted string for inclusion in LLM prompt
        """
        lines = [
            f"Base Reference: {self.base_reference}",
            "",
            "Construction Sequence:",
        ]
        for i, step in enumerate(self.construction_sequence, 1):
            lines.append(f"  {i}. {step}")
        
        if self.parameters:
            lines.append("")
            lines.append("Parameters:")
            for name, param in self.parameters.items():
                dep = f" (depends on {param.depends_on})" if param.depends_on else ""
                lines.append(f"  - {name}: {param.default}{param.unit}{dep}")
        
        if self.assumptions:
            lines.append("")
            lines.append("Assumptions:")
            for assumption in self.assumptions:
                lines.append(f"  - {assumption}")
        
        if self.manufacturing_constraints:
            lines.append("")
            lines.append("Manufacturing Constraints:")
            for constraint in self.manufacturing_constraints:
                lines.append(f"  - {constraint}")
        
        return "\n".join(lines)
    
    def get_resolved_parameters(self) -> Dict[str, float]:
        """
        Get all parameter values resolved to floats.
        Dependencies are resolved using the default values.
        
        Returns:
            Dict mapping parameter names to resolved float values
        """
        resolved = {}
        
        # First pass: add all non-dependent parameters
        for name, param in self.parameters.items():
            if not param.depends_on:
                resolved[name] = param.default
        
        # Second pass: resolve dependencies (simple linear resolution)
        # For more complex dependencies, would need topological sort
        for name, param in self.parameters.items():
            if param.depends_on and param.depends_on in resolved:
                resolved[name] = param.default
            elif name not in resolved:
                resolved[name] = param.default
        
        return resolved
