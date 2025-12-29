"""
Unified generation result contract for V1 and V2 pipelines.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Dict, Any


@dataclass
class GenerationResult:
    """
    Canonical result from any CAD generation pipeline.
    Enables uniform handling across V1 (intent-based) and V2 (LLM-based).
    
    Attributes:
        geometry_path: Path to the generated geometry file
        format: Output format (glb, step, stl)
        metadata: Additional information about the generation
        source: Which pipeline generated this (v1 or v2)
    """
    geometry_path: Path
    format: Literal["glb", "step", "stl"]
    metadata: Dict[str, Any]
    source: Literal["v1", "v2"]
    
    def to_dict(self) -> dict:
        """
        Convert to dictionary for FastAPI response serialization.
        
        Returns:
            Dictionary with serialized fields
        """
        return {
            "geometry_url": str(self.geometry_path),
            "format": self.format,
            "metadata": self.metadata,
            "source": self.source
        }
