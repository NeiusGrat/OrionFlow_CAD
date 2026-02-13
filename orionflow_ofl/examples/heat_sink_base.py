"""Heat sink base plate 150x50x8 with grid of holes — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Heat sink base plate with mounting hole grid
width = 150
height = 50
thickness = 8
hole_dia = 4.2  # M4 clearance

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Grid of holes - 5 columns x 3 rows
hole_positions = []
for col in range(-2, 3):  # -2, -1, 0, 1, 2
    for row in range(-1, 2):  # -1, 0, 1
        hole_positions.append((col * 25, row * 15))

part -= (
    Hole(hole_dia)
    .at(*hole_positions[0])
    .at(*hole_positions[1])
    .at(*hole_positions[2])
    .at(*hole_positions[3])
    .at(*hole_positions[4])
    .at(*hole_positions[5])
    .at(*hole_positions[6])
    .at(*hole_positions[7])
    .at(*hole_positions[8])
    .at(*hole_positions[9])
    .at(*hole_positions[10])
    .at(*hole_positions[11])
    .at(*hole_positions[12])
    .at(*hole_positions[13])
    .at(*hole_positions[14])
    .through()
    .label("mounting_holes")
)

export(part, "heat_sink_base.step")
print("OK  heat_sink_base.step")
