"""Thin sheet 200x100x1mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Thin sheet metal blank
width = 200
height = 100
thickness = 1

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "thin_sheet.step")
print("OK  thin_sheet.step")
