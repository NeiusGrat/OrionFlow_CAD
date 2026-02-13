"""Metric bolt pattern plate with M8 ISO clearance holes (8.4mm) — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# ============ PARAMETERS ============
# M8 bolt specifications
bolt_size = "M8"
clearance_hole_dia = 8.4  # ISO clearance hole for M8 bolt
bolt_count = 4
bolt_spacing_x = 60
bolt_spacing_y = 40
# Plate dimensions
width = 100
height = 70
thickness = 6
# ====================================

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# M8 bolt pattern - 4 holes in rectangular pattern
part -= (
    Hole(clearance_hole_dia)
    .at(bolt_spacing_x / 2, bolt_spacing_y / 2)
    .at(-bolt_spacing_x / 2, bolt_spacing_y / 2)
    .at(-bolt_spacing_x / 2, -bolt_spacing_y / 2)
    .at(bolt_spacing_x / 2, -bolt_spacing_y / 2)
    .through()
    .label(f"{bolt_size}_bolt_holes")
)

export(part, "metric_bolt_pattern.step")
print("OK  metric_bolt_pattern.step")
