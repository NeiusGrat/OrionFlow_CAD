"""Square plate 100x100x5mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Simple square plate
width = 100
height = 100
thickness = 5

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "square_plate.step")
print("OK  square_plate.step")
