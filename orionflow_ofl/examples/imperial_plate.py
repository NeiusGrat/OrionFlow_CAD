"""Imperial plate with dimensions in inches (converted to mm) — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# ============ PARAMETERS (in inches) ============
width_in = 4.0       # Width in inches
height_in = 2.0      # Height in inches
thickness_in = 0.25  # Thickness in inches
hole_dia_in = 0.25   # Hole diameter in inches (1/4")
hole_spacing_in = 3.0  # Hole spacing in inches
# ================================================

# Convert to millimeters (1 inch = 25.4mm)
INCH_TO_MM = 25.4
width = width_in * INCH_TO_MM
height = height_in * INCH_TO_MM
thickness = thickness_in * INCH_TO_MM
hole_dia = hole_dia_in * INCH_TO_MM
hole_spacing = hole_spacing_in * INCH_TO_MM

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Two mounting holes
part -= (
    Hole(hole_dia)
    .at(-hole_spacing / 2, 0)
    .at(hole_spacing / 2, 0)
    .through()
    .label("mounting_holes")
)

export(part, "imperial_plate.step")
print("OK  imperial_plate.step")
