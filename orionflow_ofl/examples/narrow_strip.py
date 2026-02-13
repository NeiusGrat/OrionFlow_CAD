"""Narrow strip 200x20x3mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Narrow strip for bracing or edge reinforcement
width = 200
height = 20
thickness = 3

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "narrow_strip.step")
print("OK  narrow_strip.step")
