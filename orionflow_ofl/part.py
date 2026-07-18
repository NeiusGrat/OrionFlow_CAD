"""OFL Part - wraps a build123d solid with boolean add/subtract support."""

from __future__ import annotations

from build123d import Cylinder as _Cylinder, Pos as _Pos, Rot as _Rot

from .internal.errors import GeometryError
from .internal.selectors import get_axis_extent


class Part:
    """Wraps a build123d solid.

    Supports:
    - ``part += other_part`` for additive boolean union
    - ``part -= hole`` for subtractive cuts
    """

    def __init__(self, solid):
        self._solid = solid

    def __iadd__(self, other):
        if not isinstance(other, Part):
            raise TypeError(f"Can only add a Part to a Part, got {type(other).__name__}")

        solid = self._solid + other._solid
        if solid is None:
            raise GeometryError("Boolean union produced no geometry")

        # A union that yields multiple disconnected bodies is almost always a
        # placement bug — typically cumulative .translate() calls on a piece
        # reused across loop iterations (transforms MUTATE the part).
        try:
            n_bodies = len(solid.solids())
        except Exception:
            n_bodies = 1
        if n_bodies > 1:
            bb = self._solid.bounding_box()
            ob = other._solid.bounding_box()
            raise GeometryError(
                f"Union produced {n_bodies} disconnected bodies — the added piece "
                "does not touch the part. Pieces must overlap or share a face. "
                f"Part spans X [{bb.min.X:g}, {bb.max.X:g}], Y [{bb.min.Y:g}, {bb.max.Y:g}], "
                f"Z [{bb.min.Z:g}, {bb.max.Z:g}]; piece spans X [{ob.min.X:g}, {ob.max.X:g}], "
                f"Y [{ob.min.Y:g}, {ob.max.Y:g}], Z [{ob.min.Z:g}, {ob.max.Z:g}]. "
                "Note: .translate()/.rotate() MUTATE the part they are called on — "
                "inside a loop, create the piece inside the loop body (or use .copy())."
            )

        self._solid = solid
        return self

    def copy(self) -> Part:
        """Independent copy — use before transforming a piece you will reuse."""
        import copy as _copy

        return Part(_copy.deepcopy(self._solid))

    def __add__(self, other):
        """Binary union: ``base + boss`` returns a new Part."""
        result = Part(self._solid)
        result += other
        return result

    def __sub__(self, other):
        """Binary subtraction: ``plate - hole`` or ``plate - slot_part``."""
        result = Part(self._solid)
        result -= other
        return result

    def translate(self, x: float = 0, y: float = 0, z: float = 0) -> Part:
        """Move the part by (x, y, z) mm in the global frame."""
        self._solid = _Pos(x, y, z) * self._solid
        return self

    def at(self, x: float = 0, y: float = 0, z: float = 0) -> Part:
        """Position a part built at the origin: alias of translate()."""
        return self.translate(x, y, z)

    def rotate(self, angle: float, axis="z") -> Part:
        """Rotate the part *angle* degrees about a global axis through the origin.

        axis: "x" | "y" | "z" (a build123d Axis is also accepted).
        """
        from build123d import Axis as _Axis

        if isinstance(axis, str):
            try:
                axis = {"x": _Axis.X, "y": _Axis.Y, "z": _Axis.Z}[axis.lower()]
            except KeyError:
                raise ValueError(f'Unknown axis: {axis!r} — use "x", "y", or "z"')
        self._solid = self._solid.rotate(axis, angle)
        return self

    def fillet(self, radius: float, edges: str = "all") -> Part:
        """Round edges of the solid. edges: 'all' | 'top' | 'bottom' | 'vertical'"""
        from build123d import fillet as _fillet, Axis as _Axis
        
        target_edges = self._solid.edges()
        if edges == "vertical":
            target_edges = target_edges.filter_by(_Axis.Z)
        elif edges == "top":
            target_edges = self._solid.faces().sort_by(_Axis.Z)[-1].edges()
        elif edges == "bottom":
            target_edges = self._solid.faces().sort_by(_Axis.Z)[0].edges()
        elif edges != "all":
            raise ValueError(f"Unknown edge selector: {edges}")
            
        self._solid = _fillet(target_edges, radius=radius)
        return self

    def chamfer(self, distance: float, edges: str = "all") -> Part:
        """Chamfer edges of the solid. edges: 'all' | 'top' | 'bottom' | 'vertical'"""
        from build123d import chamfer as _chamfer, Axis as _Axis
        
        target_edges = self._solid.edges()
        if edges == "vertical":
            target_edges = target_edges.filter_by(_Axis.Z)
        elif edges == "top":
            target_edges = self._solid.faces().sort_by(_Axis.Z)[-1].edges()
        elif edges == "bottom":
            target_edges = self._solid.faces().sort_by(_Axis.Z)[0].edges()
        elif edges != "all":
            raise ValueError(f"Unknown edge selector: {edges}")
            
        self._solid = _chamfer(target_edges, length=distance)
        return self

    def shell(self, wall_thickness: float, open_face: str | None = "top") -> Part:
        """Hollow out the solid. open_face: 'top' | 'bottom' | None (fully closed)"""
        from build123d import offset as _offset, Axis as _Axis

        if open_face is None:
            # build123d's offset with no openings returns the SHRUNKEN interior
            # solid, not a hollow shell — subtract it to get the closed shell.
            inner = _offset(self._solid, amount=-wall_thickness)
            if inner is None or inner.volume <= 0:
                raise GeometryError(
                    f"shell({wall_thickness}) leaves no interior cavity — the "
                    "walls consume the whole part; reduce the wall thickness"
                )
            hollow = self._solid - inner
            if hollow is None or hollow.volume <= 0:
                raise GeometryError("Closed shell produced no geometry")
            self._solid = hollow
            return self

        if open_face == "top":
            openings = self._solid.faces().sort_by(_Axis.Z)[-1:]
        elif open_face == "bottom":
            openings = self._solid.faces().sort_by(_Axis.Z)[0:1]
        else:
            raise ValueError(f"Unknown face selector: {open_face}")

        # build123d offset: negative amount = hollow inwards
        self._solid = _offset(self._solid, amount=-wall_thickness, openings=openings)
        return self
    def __isub__(self, other):
        from .hole import Hole

        if isinstance(other, Part):
            return self._subtract_part(other)
        if isinstance(other, Hole):
            return self._subtract_hole(other)
        raise TypeError(
            f"Can only subtract a Hole or a Part from a Part, got {type(other).__name__}"
        )

    def _subtract_part(self, other: Part) -> Part:
        """Cut another Part's solid out of this one (slots, pockets, cutouts)."""
        cut = self._solid - other._solid
        if cut is None:
            raise GeometryError("Boolean subtraction produced no geometry")

        if abs(self._solid.volume - cut.volume) < max(self._solid.volume, 1.0) * 1e-9:
            bb = self._solid.bounding_box()
            ob = other._solid.bounding_box()
            raise GeometryError(
                "Part subtraction removed no material — the cutter does not overlap "
                f"the part. Part spans X [{bb.min.X:g}, {bb.max.X:g}], "
                f"Y [{bb.min.Y:g}, {bb.max.Y:g}], Z [{bb.min.Z:g}, {bb.max.Z:g}]; "
                f"cutter spans X [{ob.min.X:g}, {ob.max.X:g}], "
                f"Y [{ob.min.Y:g}, {ob.max.Y:g}], Z [{ob.min.Z:g}, {ob.max.Z:g}]. "
                "Position the cutter with .at()/.translate() so the volumes overlap."
            )
        self._solid = cut
        return self

    def _subtract_hole(self, hole) -> Part:
        if not hole._positions:
            raise GeometryError("Hole has no positions - call .at() or .at_circular() first")

        radius = hole._diameter / 2
        axis = hole._axis
        lo, hi = get_axis_extent(self._solid, axis)

        if hole._through:
            depth = (hi - lo) + 2.0  # 1 mm buffer each side
        elif hole._depth is not None:
            depth = hole._depth
        else:
            raise GeometryError("Hole depth not set - call .through() or .to_depth(d)")

        # Blind holes enter from a face of the drill axis: "top" = max side
        # (default), "bottom" = min side (e.g. the far end wall of a tube).
        if hole._through:
            axis_center = (lo + hi) / 2
        elif getattr(hole, "_from_face", "top") == "bottom":
            axis_center = lo + depth / 2
        else:
            axis_center = hi - depth / 2

        # The Cylinder's own axis is Z; rotate it onto the drill axis, and map
        # the 2-tuple position onto the two remaining global axes in order:
        #   z → (x, y) · x → (y, z) · y → (x, z)
        solid = self._solid
        for u, v in hole._positions:
            if axis == "z":
                loc = _Pos(u, v, axis_center)
            elif axis == "x":
                loc = _Pos(axis_center, u, v) * _Rot(0, 90, 0)
            else:  # "y"
                loc = _Pos(u, axis_center, v) * _Rot(90, 0, 0)
            cyl = loc * _Cylinder(radius, depth)
            cut = solid - cyl

            if cut is None:
                raise GeometryError("Boolean subtraction produced no geometry")

            # A cut that removes no material means the hole missed the part —
            # almost always center-origin coordinates mistaken for corner-origin.
            if abs(solid.volume - cut.volume) < max(solid.volume, 1.0) * 1e-9:
                label = f" '{hole._label}'" if hole._label else ""
                bb = solid.bounding_box()
                plane_axes = {"z": "XY", "x": "YZ", "y": "XZ"}[axis]
                raise GeometryError(
                    f"Hole{label} d={hole._diameter} along {axis.upper()} at "
                    f"({u:g}, {v:g}) on the {plane_axes} plane does not cut the part. "
                    f"The part spans X [{bb.min.X:g}, {bb.max.X:g}], "
                    f"Y [{bb.min.Y:g}, {bb.max.Y:g}], Z [{bb.min.Z:g}, {bb.max.Z:g}]. "
                    f"Hole coordinates are measured from the part CENTER (0, 0), not a corner."
                )
            solid = cut

        self._solid = solid
        return self
