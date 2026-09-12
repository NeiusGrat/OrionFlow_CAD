"""Mutation: a fillet radius larger than the edge it rounds. Confirmed in
this repo (CLAUDE.md build123d gotchas, F6 in OF-TR-002 §3) to raise a
catchable ValueError rather than aborting the process -- must be classified
exec_crash, not a harness error, and the worker process must survive to
serve the next job."""

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .rect(40, 40)
    .extrude(10)
)
part.fillet(30)
