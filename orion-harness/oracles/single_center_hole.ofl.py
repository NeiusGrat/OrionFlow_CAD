"""Plate with single center hole — OFL v0.1 example."""

from orionflow_ofl import *

# Rectangular plate with one centered hole
width = 100
height = 60
thickness = 5
hole_dia = 15

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at(0, 0)
    .through()
    .label("center_hole")
)
