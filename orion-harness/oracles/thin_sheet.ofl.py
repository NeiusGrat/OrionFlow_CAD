"""Thin sheet 200x100x1mm — OFL v0.1 example."""

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
