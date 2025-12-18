import cadquery as cq
from cadquery import exporters


def make_model():
    """
    Creates a simple parametric solid.
    """
    return (
        cq.Workplane("XY")
        .circle(20)      # radius = 20 mm
        .extrude(10)     # height = 10 mm
    )


if __name__ == "__main__":
    model = make_model()

    exporters.export(model, "model.step")
    exporters.export(model, "model.stl")

    print("✅ CAD files generated: model.step, model.stl")
