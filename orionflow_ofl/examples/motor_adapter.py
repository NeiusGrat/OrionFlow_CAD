"""Motor adapter plate with two bolt circles — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Motor adapter - connects motor to gearbox with different bolt patterns
plate_dia = 100
thickness = 12
bore_dia = 30

# Motor side (inner) - NEMA 23 pattern
motor_bolt_dia = 5.5
motor_pcd = 47.14

# Gearbox side (outer) - larger pattern
gearbox_bolt_dia = 7
gearbox_pcd = 80

part = (
    Sketch(Plane.XY)
    .circle(plate_dia)
    .extrude(thickness)
)

# Center bore
part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("shaft_bore")
)

# Motor side bolt holes (inner circle)
part -= (
    Hole(motor_bolt_dia)
    .at_circular(motor_pcd / 2, count=4, start_angle=45)
    .through()
    .label("motor_bolts")
)

# Gearbox side bolt holes (outer circle)
part -= (
    Hole(gearbox_bolt_dia)
    .at_circular(gearbox_pcd / 2, count=6, start_angle=0)
    .through()
    .label("gearbox_bolts")
)

export(part, "motor_adapter.step")
print("OK  motor_adapter.step")
