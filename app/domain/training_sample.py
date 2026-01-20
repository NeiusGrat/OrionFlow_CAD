"""
Training Sample - Comprehensive training data model for LLM fine-tuning.

==============================================================================
ARCHITECTURE: Gold Dataset for Fine-Tuning
==============================================================================

This module captures the complete pipeline state for future LLM training:
- Input: prompt
- Intelligence Layer: ConstructionPlan (upstream reasoning)
- Execution Layer: FeatureGraph (mechanical operations)
- Results: compile success, geometry metrics
- Debug Info: raw LLM response, JSON parse status, repair applied

The resulting JSONL dataset enables:
1. Supervised fine-tuning on successful generations
2. RLHF using compile success as reward signal
3. Error analysis on failure cases
"""
from typing import Dict, Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class GeometryMetrics(BaseModel):
    """
    Computed geometry properties for quality assessment.
    
    These metrics serve as:
    1. RL reward signals (volume > 0, is_manifold = True)
    2. Quality filters for training data
    3. Manufacturing validation (min thickness, etc.)
    """
    volume: float = Field(description="Volume in mm³")
    surface_area: float = Field(description="Surface area in mm²")
    bounding_box: Dict[str, float] = Field(
        default_factory=dict,
        description="Axis-aligned bounding box: x_min, x_max, y_min, y_max, z_min, z_max"
    )
    is_valid: bool = Field(description="Build123d/OpenCASCADE validity check")
    is_manifold: bool = Field(description="Watertight manifold mesh")
    face_count: int = Field(default=0, description="Number of faces in B-Rep")
    edge_count: int = Field(default=0, description="Number of edges in B-Rep")
    vertex_count: int = Field(default=0, description="Number of vertices")
    
    @classmethod
    def empty(cls) -> "GeometryMetrics":
        """Return empty metrics for failed compilations."""
        return cls(
            volume=0.0,
            surface_area=0.0,
            bounding_box={},
            is_valid=False,
            is_manifold=False,
            face_count=0,
            edge_count=0,
            vertex_count=0
        )


class TrainingSample(BaseModel):
    """
    Complete training sample capturing the full CAD generation pipeline.
    
    This is the gold standard format for LLM fine-tuning datasets.
    Each sample captures:
    - What the user asked for (prompt)
    - How we planned to build it (construction_plan)
    - What operations we generated (feature_graph)
    - Whether it compiled successfully (compile_success)
    - Geometric properties of the result (geometry_metrics)
    """
    # Identification
    sample_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique sample identifier"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO format timestamp"
    )
    
    # =========================================================================
    # INPUT LAYER
    # =========================================================================
    prompt: str = Field(description="Original user prompt")
    
    # =========================================================================
    # INTELLIGENCE LAYER (Upstream - All reasoning lives here)
    # =========================================================================
    construction_plan: Dict[str, Any] = Field(
        default_factory=dict,
        description="Full ConstructionPlan serialized - the intelligence boundary"
    )
    
    # =========================================================================
    # EXECUTION LAYER (Mechanical operations only)
    # =========================================================================
    feature_graph: Dict[str, Any] = Field(
        default_factory=dict,
        description="FeatureGraph IR - executable geometry graph"
    )
    feature_graph_version: str = Field(
        default="v1",
        description="FeatureGraph schema version (v1, v2, v3)"
    )
    
    # =========================================================================
    # COMPILATION RESULTS
    # =========================================================================
    compile_success: bool = Field(description="Whether compilation succeeded")
    compile_error: Optional[str] = Field(
        None,
        description="Error message if compilation failed"
    )
    execution_trace: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed execution trace from compiler"
    )
    retry_count: int = Field(
        default=0,
        description="Number of LLM retries before this result"
    )
    
    # =========================================================================
    # GEOMETRY METRICS (Only populated on success)
    # =========================================================================
    geometry_metrics: Optional[GeometryMetrics] = Field(
        None,
        description="Computed geometry properties (volume, surface area, etc.)"
    )
    
    # =========================================================================
    # LLM DEBUG INFO (For JSON enforcement analysis)
    # =========================================================================
    llm_model: str = Field(
        default="unknown",
        description="LLM model used for generation"
    )
    llm_raw_response: str = Field(
        default="",
        description="Raw LLM response before parsing (for debugging)"
    )
    json_parse_success: bool = Field(
        default=True,
        description="Whether JSON parsing succeeded without repair"
    )
    json_repair_applied: bool = Field(
        default=False,
        description="Whether auto-repair was needed for JSON"
    )
    json_validation_errors: List[str] = Field(
        default_factory=list,
        description="Schema validation errors if any"
    )
    
    # =========================================================================
    # QUALITY MARKERS
    # =========================================================================
    backend: str = Field(
        default="build123d",
        description="CAD backend used (build123d, onshape)"
    )
    is_synthetic: bool = Field(
        default=False,
        description="Whether this is synthetic training data"
    )
    quality_score: float = Field(
        default=0.0,
        description="Computed quality score 0.0-1.0"
    )
    
    def to_training_dict(self) -> Dict[str, Any]:
        """
        Convert to training format (prompt, completion pairs).
        
        Returns:
            Dict with 'prompt' and 'completion' keys for fine-tuning
        """
        return {
            "prompt": self.prompt,
            "completion": self.feature_graph,
            "metadata": {
                "sample_id": self.sample_id,
                "compile_success": self.compile_success,
                "geometry_metrics": self.geometry_metrics.model_dump() if self.geometry_metrics else None,
                "construction_plan": self.construction_plan,
                "quality_score": self.quality_score
            }
        }
    
    def calculate_quality_score(self) -> float:
        """
        Calculate quality score based on compilation success and geometry.
        
        Score factors:
        - Compile success: 0.5 base
        - Valid geometry: 0.2
        - Manifold: 0.1
        - Volume > 0: 0.1
        - Clean JSON (no repair): 0.1
        """
        score = 0.0
        
        if self.compile_success:
            score += 0.5
            
        if self.geometry_metrics:
            if self.geometry_metrics.is_valid:
                score += 0.2
            if self.geometry_metrics.is_manifold:
                score += 0.1
            if self.geometry_metrics.volume > 0:
                score += 0.1
                
        if self.json_parse_success and not self.json_repair_applied:
            score += 0.1
            
        return min(score, 1.0)
