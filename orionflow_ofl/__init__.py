"""OrionFlow Language (OFL) v0.1 — deterministic Python CAD DSL.

Public API (Phase 1):
    Plane       — XY, XZ, YZ
    Sketch      — .rect() / .rounded_rect() / .circle() → .extrude() → Part
    Part        — supports  part -= hole
    Hole        — .at() / .at_circular() / .through() / .to_depth() / .label()
    export()    — write Part to .step or .stl
"""

from .planes import Plane
from .sketch import Sketch
from .part import Part
from .hole import Hole
from .export import export

__all__ = ["Plane", "Sketch", "Part", "Hole", "export"]
__version__ = "0.2.0"
