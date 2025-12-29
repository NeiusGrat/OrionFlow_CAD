import cadquery as cq
from app.cad.legacy.base_part import BasePart

class BoxPart(BasePart):
    def build(self) -> cq.Workplane:
        return (
            cq.Workplane("XY")
            .box(
                self.params["length"],
                self.params["width"],
                self.params["height"]
            )
        )
