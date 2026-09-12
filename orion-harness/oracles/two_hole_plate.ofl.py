"""Plate with two holes spaced apart — OFL v0.1 example."""

from orionflow_ofl import *

# Rectangular plate with two mounting holes
width = 120
height = 50
thickness = 6
hole_dia = 8
hole_spacing = 80

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at(-hole_spacing / 2, 0)
    .at(hole_spacing / 2, 0)
    .through()
    .label("mounting_holes")
)
