"""Parametric standoff with thread_dia, od, length as variables — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# ============ PARAMETERS ============
thread_dia = 5       # Thread diameter for clearance (M5 = 5.3mm typical)
od = 12             # Outer diameter (mm)
length = 20         # Standoff length/height (mm)
# ====================================

# Calculate clearance hole (thread dia + 0.3mm for typical fit)
clearance_dia = thread_dia + 0.3

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(length)
)

part -= (
    Hole(clearance_dia)
    .at(0, 0)
    .through()
    .label("thread_clearance")
)

export(part, "parametric_standoff.step")
print("OK  parametric_standoff.step")
