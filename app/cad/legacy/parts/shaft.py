import cadquery as cq
from app.cad.legacy.base_part import BasePart

class ShaftPart(BasePart):
    def build(self) -> cq.Workplane:
        # Shaft is just a cylinder usually, maybe with chamfers in future
        # For now, implemented as a tall cylinder
        return (
            cq.Workplane("XY")
            .cylinder(
                self.params["height"],
                self.params["radius"]
            )
        )
