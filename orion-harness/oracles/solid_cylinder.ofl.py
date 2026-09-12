"""Solid cylinder without holes — OFL v0.1 example."""

from orionflow_ofl import *

# Simple solid cylinder - no center bore
diameter = 40
height = 30

part = (
    Sketch(Plane.XY)
    .circle(diameter)
    .extrude(height)
)
