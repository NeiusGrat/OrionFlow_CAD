import cadquery as cq
from app.cad.base_part import BasePart

class Cylinder(BasePart):
    def build(self) -> cq.Workplane:
        return (
            cq.Workplane("XY")
            .cylinder(
                self.params["height"],
                self.params["radius"]
            )
        )
