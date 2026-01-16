"""
Compilers package - Converts FeatureGraph to geometry files.

Clean separation of geometry compilation from business logic.
Each compiler is responsible for one output target.

Available compilers:
- BaseCompiler: Abstract base class with shared functionality
- Build123dCompiler: V1 compiler for STEP/STL/GLB export
- Build123dCompilerV2: V2 compiler with semantic selector support
- Build123dCompilerV3: V3 compiler with topological identity tracking (Phase 2)
"""
from .base_compiler import BaseCompiler, BuildContext
from .build123d_compiler import Build123dCompiler
from .build123d_compiler_v2 import Build123dCompilerV2
from .build123d_compiler_v3 import Build123dCompilerV3

__all__ = [
    "BaseCompiler",
    "BuildContext",
    "Build123dCompiler", 
    "Build123dCompilerV2", 
    "Build123dCompilerV3"
]
