"""Plate with holes at non-symmetric positions — OFL v0.1 example."""

from orionflow_ofl import *

# Plate with asymmetrically placed holes - real-world mounting pattern
width = 120
height = 80
thickness = 6
hole_dia = 5

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Asymmetric hole positions
part -= (
    Hole(hole_dia)
    .at(45, 30)
    .at(-50, 25)
    .at(-30, -20)
    .at(40, -35)
    .at(10, 10)
    .through()
    .label("asymmetric_holes")
)
