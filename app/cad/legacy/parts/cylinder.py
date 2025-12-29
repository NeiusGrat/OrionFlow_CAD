import cadquery as cq
from app.cad.legacy.base_part import BasePart

class CylinderPart(BasePart):
    def build(self) -> cq.Workplane:
        return (
            cq.Workplane("XY")
            .cylinder(
                self.params["height"],
                self.params["radius"]
            )
        )
