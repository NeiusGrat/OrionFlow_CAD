"""OFL Hole — declarative subtractive cylinder specification."""

import math


class Hole:
    """Describe one or more cylindrical holes to subtract from a Part.

    Geometry is built only when applied via ``part -= hole``.
    """

    def __init__(self, diameter):
        self._diameter = diameter
        self._positions = []
        self._through = False
        self._depth = None
        self._label = None
        self._axis = "z"
        self._from_face = "top"

    # ── positioning ──────────────────────────────────────────────

    def at(self, x, y, z=None):
        """Add a single hole position (XY relative to part center).

        With .along("x") the pair is read as (y, z); with .along("y") as (x, z).
        A third coordinate is accepted and ignored: holes always drill from the
        outer face of the drill axis, so only the two cross-axis coordinates
        place them (LLMs habitually pass a z — a crash helps nobody).
        """
        self._positions.append((x, y))
        return self

    def along(self, axis):
        """Drill direction: "z" (default, top-down), "x", or "y" (side holes).

        Position coordinates are the two remaining axes in order:
        along("z") → .at(x, y) · along("x") → .at(y, z) · along("y") → .at(x, z)
        """
        axis = str(axis).lower()
        if axis not in ("x", "y", "z"):
            raise ValueError(f'Unknown hole axis: {axis!r} — use "x", "y", or "z"')
        self._axis = axis
        return self

    def at_circular(self, radius, count, start_angle=0):
        """Add *count* holes equally spaced on a circle of *radius* mm."""
        for i in range(count):
            angle = math.radians(start_angle + i * 360 / count)
            self._positions.append((radius * math.cos(angle), radius * math.sin(angle)))
        return self

    # ── depth ────────────────────────────────────────────────────

    def through(self):
        """Mark hole as through-all (depth derived from part bounding box)."""
        self._through = True
        self._depth = None
        return self

    def to_depth(self, depth, from_face="top"):
        """Blind hole *depth* mm deep, entering from *from_face*:
        "top" (max face of the drill axis, default) or "bottom" (min face)."""
        if from_face not in ("top", "bottom"):
            raise ValueError(
                f'Unknown from_face: {from_face!r} — use "top" or "bottom"'
            )
        self._through = False
        self._depth = depth
        self._from_face = from_face
        return self

    # ── common LLM mistakes, redirected instead of crashing ──────

    def translate(self, *args, **kwargs):
        from .internal.errors import GeometryError

        raise GeometryError(
            "Hole has no .translate() — position holes with .at(x, y) / "
            ".at_circular(); drill from the far side with "
            '.to_depth(depth, from_face="bottom"); a hole through both end '
            "walls of a tube is ONE .through() hole."
        )

    # ── metadata ─────────────────────────────────────────────────

    def label(self, name):
        """Attach a human-readable label (stored, not used for geometry)."""
        self._label = name
        return self
