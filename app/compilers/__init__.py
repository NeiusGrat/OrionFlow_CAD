"""
Compilers package - Converts FeatureGraph to geometry files.

Clean separation of geometry compilation from business logic.
Each compiler is responsible for one output target.

Available compilers:
- BaseCompiler: Abstract base class with shared functionality
- Build123dCompiler: V1 compiler for STEP/STL/GLB export
- Build123dCompilerV2: V2 compiler with semantic selector support
- Build123dCompilerV3: V3 compiler with topological identity tracking (Phase 2)

Every name below is resolved on first use rather than at import. Each of these
modules imports build123d, and build123d imports 542 OCP modules — so merely
naming this package used to cost a two-minute cold start, including in processes
that only wanted ``BuildContext``.
"""

from typing import Any

_LAZY = {
    "BaseCompiler": ".base_compiler",
    "BuildContext": ".base_compiler",
    "Build123dCompiler": ".build123d_compiler",
    "Build123dCompilerV2": ".build123d_compiler_v2",
    "Build123dCompilerV3": ".build123d_compiler_v3",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module, __name__), name)


__all__ = [
    "BaseCompiler",
    "BuildContext",
    "Build123dCompiler",
    "Build123dCompilerV2",
    "Build123dCompilerV3",
]
