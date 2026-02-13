"""Rectangular plate 150x80x4mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Rectangular plate for general purpose use
width = 150
height = 80
thickness = 4

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "rectangular_plate.step")
print("OK  rectangular_plate.step")
