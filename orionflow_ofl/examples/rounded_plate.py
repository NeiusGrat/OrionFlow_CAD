"""Rounded rectangle plate 120x80x6mm with 8mm corner radius — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Rounded plate for aesthetic or safety-critical edges
width = 120
height = 80
corner_radius = 8
thickness = 6

part = (
    Sketch(Plane.XY)
    .rounded_rect(width, height, corner_radius)
    .extrude(thickness)
)

export(part, "rounded_plate.step")
print("OK  rounded_plate.step")
