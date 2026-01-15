"""
Validators Package - Geometry Verification Passes

Exports all validators for use in compilation pipeline.
"""
from app.compilers.validators.zero_thickness import ZeroThicknessValidator
from app.compilers.validators.fillet_validator import FilletValidator
from app.compilers.validators.self_intersection import SelfIntersectionValidator
from app.compilers.validators.degenerate_face import DegenerateFaceValidator

__all__ = [
    "GeometryValidator",
    "ZeroThicknessValidator",
    "FilletValidator",
    "SelfIntersectionValidator",
    "DegenerateFaceValidator"
]

# Export base class from package root
from app.compilers.validators import GeometryValidator
