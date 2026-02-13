"""Servo mounting bracket with offset hole pattern — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Standard servo bracket (fits common hobby servos)
width = 60
height = 40
thickness = 3
mount_hole_dia = 4.2  # M4 clearance
servo_hole_spacing_x = 48
servo_hole_spacing_y = 10

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Servo mounting holes - offset pattern
part -= (
    Hole(mount_hole_dia)
    .at(servo_hole_spacing_x / 2, servo_hole_spacing_y / 2)
    .at(-servo_hole_spacing_x / 2, servo_hole_spacing_y / 2)
    .at(-servo_hole_spacing_x / 2, -servo_hole_spacing_y / 2)
    .at(servo_hole_spacing_x / 2, -servo_hole_spacing_y / 2)
    .through()
    .label("servo_mount_holes")
)

# Bracket mounting holes
part -= (
    Hole(3.4)  # M3 clearance
    .at(25, 15)
    .at(-25, 15)
    .at(25, -15)
    .at(-25, -15)
    .through()
    .label("bracket_mount_holes")
)

export(part, "servo_bracket.step")
print("OK  servo_bracket.step")
