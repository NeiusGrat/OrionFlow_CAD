"""Thick block 50x50x30mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Thick square block for structural applications
width = 50
height = 50
thickness = 30

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "thick_block.step")
print("OK  thick_block.step")
