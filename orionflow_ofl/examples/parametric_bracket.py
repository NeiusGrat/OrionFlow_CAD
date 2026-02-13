"""Parametric bracket with width/height/thickness/hole_count as variables — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# ============ PARAMETERS ============
width = 100         # Bracket width (mm)
height = 60         # Bracket height (mm)
thickness = 5       # Bracket thickness (mm)
hole_count = 4      # Number of mounting holes (2, 4, or 6)
hole_dia = 6        # Hole diameter (mm)
corner_r = 5        # Corner radius (mm)
# ====================================

part = (
    Sketch(Plane.XY)
    .rounded_rect(width, height, corner_r)
    .extrude(thickness)
)

# Generate hole positions based on hole_count
if hole_count >= 2:
    part -= (
        Hole(hole_dia)
        .at(width / 2 - 15, 0)
        .at(-width / 2 + 15, 0)
        .through()
        .label("side_holes")
    )

if hole_count >= 4:
    part -= (
        Hole(hole_dia)
        .at(width / 2 - 15, height / 2 - 12)
        .at(-width / 2 + 15, height / 2 - 12)
        .through()
        .label("top_holes")
    )

if hole_count >= 6:
    part -= (
        Hole(hole_dia)
        .at(width / 2 - 15, -height / 2 + 12)
        .at(-width / 2 + 15, -height / 2 + 12)
        .through()
        .label("bottom_holes")
    )

export(part, "parametric_bracket.step")
print("OK  parametric_bracket.step")















