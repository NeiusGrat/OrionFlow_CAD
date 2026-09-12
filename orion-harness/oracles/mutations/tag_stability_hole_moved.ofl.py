"""Mutation: the same tag_stability plate, but the named hole's position
drifted from x=30 to x=45. Must fail tier1.hole_present when checked
against the task's declared params (at=[30,0], diameter=8), and nothing
upstream of it -- the plate itself is still a perfectly valid single
watertight solid."""

from orionflow_ofl import *

width = 100
height = 40
thickness = 6
hole_dia = 8
hole_x = 45  # drifted from the declared 30

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
