"""Rectangular plate 150x80x4mm — OFL v0.1 example."""

from orionflow_ofl import *

# Rectangular plate for general purpose use
width = 150
height = 80
thickness = 4

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)
