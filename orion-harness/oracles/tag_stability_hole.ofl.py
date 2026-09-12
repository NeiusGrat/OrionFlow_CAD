"""tag_stability: a plate with one labeled mounting hole. The task's
checks assert the hole is found at its declared position/diameter after
rebuild (tier1.hole_present) -- a smaller, geometry-only stand-in for the
product's FreeCAD-based topological-naming system, not a reimplementation
of it (R1)."""

from orionflow_ofl import *

width = 100
height = 40
thickness = 6
hole_dia = 8
hole_x = 30

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at(hole_x, 0)
    .through()
    .label("mount_hole")
)
