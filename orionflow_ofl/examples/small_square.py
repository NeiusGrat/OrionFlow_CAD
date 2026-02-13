"""Small square plate 20x20x2mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Small square plate for shim or spacer use
width = 20
height = 20
thickness = 2

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "small_square.step")
print("OK  small_square.step")
