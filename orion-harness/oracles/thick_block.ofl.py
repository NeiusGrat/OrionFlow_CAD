"""Thick block 50x50x30mm — OFL v0.1 example."""

from orionflow_ofl import *

# Thick square block for structural applications
width = 50
height = 50
thickness = 30

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)
