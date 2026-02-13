"""Large plate 300x200x10mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Large rectangular plate for base or mounting surface
width = 300
height = 200
thickness = 10

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "large_plate.step")
print("OK  large_plate.step")
