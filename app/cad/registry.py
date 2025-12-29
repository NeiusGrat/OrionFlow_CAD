"""
Part registry for V1 (CadQuery-based) parts.
"""
from app.cad.legacy.parts import BoxPart, CylinderPart, ShaftPart

PART_REGISTRY = {
    "box": BoxPart,
    "cylinder": CylinderPart,
    "shaft": ShaftPart
    # Gear added later
}
