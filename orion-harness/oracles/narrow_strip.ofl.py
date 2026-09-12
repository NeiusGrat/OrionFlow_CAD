"""Narrow strip 200x20x3mm — OFL v0.1 example."""

from orionflow_ofl import *

# Narrow strip for bracing or edge reinforcement
width = 200
height = 20
thickness = 3

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)
