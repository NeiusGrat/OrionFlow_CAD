"""Build123d context helpers for OFL sketch-to-solid pipeline."""

from build123d import (
    BuildPart as _BuildPart,
    BuildSketch as _BuildSketch,
    Rectangle as _Rectangle,
    RectangleRounded as _RectangleRounded,
    Circle as _Circle,
    Polygon as _Polygon,
    SlotOverall as _SlotOverall,
    extrude as _extrude,
)

from .errors import GeometryError


def build_extrusion(plane, profile_type, params, thickness):
    """Build a sketch on *plane*, apply *profile_type* with *params*, extrude by *thickness*.

    Returns a build123d Part (solid).
    """
    with _BuildPart() as bp:
        with _BuildSketch(plane):
            if profile_type == "rect":
                _Rectangle(params["width"], params["height"])
            elif profile_type == "rounded_rect":
                _RectangleRounded(
                    params["width"], params["height"], params["corner_radius"]
                )
            elif profile_type == "circle":
                _Circle(params["diameter"] / 2)
            elif profile_type == "slot":
                _SlotOverall(params["length"], params["width"])
            elif profile_type == "polygon":
                # align=None keeps vertices exactly as given (no recentering)
                _Polygon(*params["points"], align=None)
            else:
                raise GeometryError(f"Unknown profile type: {profile_type}")
        _extrude(amount=thickness)

    solid = bp.part
    if solid is None:
        raise GeometryError("Extrusion produced no solid geometry")
    return solid
