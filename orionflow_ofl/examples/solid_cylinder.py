"""Solid cylinder without holes — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Simple solid cylinder - no center bore
diameter = 40
height = 30

part = (
    Sketch(Plane.XY)
    .circle(diameter)
    .extrude(height)
)

export(part, "solid_cylinder.step")
print("OK  solid_cylinder.step")
