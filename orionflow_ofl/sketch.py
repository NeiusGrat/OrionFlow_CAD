"""OFL Sketch — 2D profile builder that extrudes to a Part."""

from .internal.errors import GeometryError


class Sketch:
    """Define a 2D profile on a plane, then extrude to a solid Part."""

    def __init__(self, plane, offset=0):
        if offset != 0:
            self._plane = plane.offset(offset)
        else:
            self._plane = plane
        self._profile = None

    # ── profile methods (mutually exclusive, last wins) ──────────

    def rect(self, width, height):
        """Axis-aligned rectangle centered on the sketch plane origin."""
        self._profile = ("rect", {"width": width, "height": height})
        return self

    def rounded_rect(self, width, height, corner_radius):
        """Rectangle with uniform corner radii."""
        self._profile = (
            "rounded_rect",
            {"width": width, "height": height, "corner_radius": corner_radius},
        )
        return self

    def circle(self, diameter):
        """Circle specified by *diameter* (converted to radius internally)."""
        self._profile = ("circle", {"diameter": diameter})
        return self

    # ── extrude ──────────────────────────────────────────────────

    def extrude(self, thickness):
        """Extrude the current profile in +Z by *thickness* mm. Returns a Part."""
        if self._profile is None:
            raise GeometryError("No profile defined — call .rect(), .rounded_rect(), or .circle() first")

        from .internal.context import build_extrusion
        from .part import Part

        profile_type, params = self._profile
        solid = build_extrusion(self._plane, profile_type, params, thickness)
        return Part(solid)
