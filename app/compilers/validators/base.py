"""
Geometry Validator Base Class

Abstract base class for all geometry validators in the compilation pipeline.
"""
from abc import ABC, abstractmethod
from typing import Optional
from build123d import Solid
from app.domain.feature_graph_v2 import FeatureV2
from app.domain.compiler_errors import CompilerError


class GeometryValidator(ABC):
    """
    Abstract base class for geometry validators.
    
    All validators must implement:
    - name: Human-readable validator name
    - validate: Check geometry and return error if invalid
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable validator name."""
        pass
    
    @abstractmethod
    def validate(self, solid: Solid, feature: FeatureV2) -> Optional[CompilerError]:
        """
        Validate geometry for a specific feature.
        
        Args:
            solid: Current geometry state (B-Rep)
            feature: Feature being validated
            
        Returns:
            CompilerError if validation fails, None if valid
        """
        pass
