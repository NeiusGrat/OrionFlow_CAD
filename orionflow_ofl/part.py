"""OFL Part - wraps a build123d solid with boolean add/subtract support."""

from __future__ import annotations

from build123d import Cylinder as _Cylinder, Pos as _Pos

from .internal.errors import GeometryError
from .internal.selectors import get_z_extent


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

        self._solid = solid
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
        """Hollow out the solid. open_face: 'top' | 'bottom' | None"""
        from build123d import offset as _offset, Axis as _Axis
        
        openings = []
        if open_face == "top":
            openings = self._solid.faces().sort_by(_Axis.Z)[-1:]
        elif open_face == "bottom":
            openings = self._solid.faces().sort_by(_Axis.Z)[0:1]
        elif open_face is not None:
            raise ValueError(f"Unknown face selector: {open_face}")
            
        # build123d offset: negative amount = hollow inwards
        self._solid = _offset(self._solid, amount=-wall_thickness, openings=openings)
        return self
    def __isub__(self, hole):
        from .hole import Hole

        if not isinstance(hole, Hole):
            raise TypeError(f"Can only subtract a Hole from a Part, got {type(hole).__name__}")

        if not hole._positions:
            raise GeometryError("Hole has no positions - call .at() or .at_circular() first")

        radius = hole._diameter / 2
        z_min, z_max = get_z_extent(self._solid)

        if hole._through:
            depth = (z_max - z_min) + 2.0  # 1 mm buffer each side
        elif hole._depth is not None:
            depth = hole._depth
        else:
            raise GeometryError("Hole depth not set - call .through() or .to_depth(d)")

        z_center = (z_min + z_max) / 2 if hole._through else (z_max - depth / 2)

        solid = self._solid
        for x, y in hole._positions:
            cyl = _Pos(x, y, z_center) * _Cylinder(radius, depth)
            solid = solid - cyl

        if solid is None:
            raise GeometryError("Boolean subtraction produced no geometry")

        self._solid = solid
        return self
