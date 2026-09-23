"""The embodiment compiler: a robot spec in, a validated robot out.

    spec -> FeatureGraph per component -> exact OpenCASCADE solids
         -> exact mass, CoM and inertia -> collision hulls
         -> URDF + MJCF + STEP -> gates, robocheck last

    python -m embodiment build [spec.json] OUT_DIR

A robot is accepted only if every gate passes. See `compiler.py`.
"""
from .compiler import compile_robot
from .spec import ArmSpec

__all__ = ["ArmSpec", "compile_robot"]
