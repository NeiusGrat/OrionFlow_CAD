"""Convert DeepCAD JSON models to OFL Python code strings."""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class DeepCADConverter:
    """Converts DeepCAD JSON -> OFL Python code string."""

    def __init__(self, scale: float = 50.0):
        self.scale = scale

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------
    def convert(self, deepcad_json: dict, model_id: str = "part") -> str | None:
        """Return OFL Python code string, or *None* if not convertible."""
        sequence = deepcad_json.get("sequence", [])
        if not sequence:
            logger.debug("skip %s: empty sequence", model_id)
            return None

        # pair up sketch + extrude
        pairs = self._pair_sketch_extrude(sequence)
        if not pairs:
            logger.debug("skip %s: no sketch/extrude pairs", model_id)
            return None

        base = None
        holes: list[dict] = []
        skipped_cuts = 0
        skipped_joins = 0

        for sketch_data, extrude_data in pairs:
            boolean = extrude_data.get("boolean", "new")
            plane_name = self._classify_plane(sketch_data.get("plane", {}))
            if plane_name is None:
                logger.debug("skip %s: non-axis-aligned plane", model_id)
                return None

            loops = sketch_data.get("loops", [])
            if len(loops) != 1:
                logger.debug("skip %s: multiple loops", model_id)
                return None
            curves = loops[0].get("curves", [])

            if boolean == "new":
                if base is not None:
                    logger.debug("skip %s: multiple 'new' extrudes", model_id)
                    return None
                profile = self._detect_profile(curves)
                if profile is None:
                    logger.debug("skip %s: non-convertible base profile", model_id)
                    return None
                extent = extrude_data.get("extent_one", 0)
                base = {
                    "plane": plane_name,
                    "profile": profile,
                    "thickness": round(extent * self.scale, 1),
                }

            elif boolean == "cut":
                if base is None:
                    logger.debug("skip %s: cut before base", model_id)
                    return None
                # only circular cuts become holes
                circle_dia = self._detect_circle(curves)
                if circle_dia is None:
                    logger.debug("skip %s: non-circular cut", model_id)
                    return None
                # only top-face cuts supported
                if plane_name != base["plane"]:
                    skipped_cuts += 1
                    continue
                cut_center = self._loop_center(curves)
                extent = extrude_data.get("extent_one", 0)
                extent_two = extrude_data.get("extent_two", 0)
                is_through = abs(extent - base["thickness"] / self.scale) < 0.05 or (
                    extent + extent_two
                ) >= (base["thickness"] / self.scale - 0.01)
                holes.append(
                    {
                        "diameter": circle_dia,
                        "x": round(cut_center[0] * self.scale, 1),
                        "y": round(cut_center[1] * self.scale, 1),
                        "through": is_through,
                        "depth": round(extent * self.scale, 1),
                    }
                )

            elif boolean == "join":
                skipped_joins += 1
                continue
            else:
                logger.debug("skip %s: unknown boolean '%s'", model_id, boolean)
                return None

        if base is None:
            logger.debug("skip %s: no base shape found", model_id)
            return None

        return self._generate_ofl_code(base, holes, skipped_cuts, skipped_joins, model_id)

    # ------------------------------------------------------------------
    # profile detection
    # ------------------------------------------------------------------
    def _detect_profile(self, curves: list) -> dict | None:
        rect = self._detect_rectangle(curves)
        if rect is not None:
            return {"type": "rect", "width": rect[0], "height": rect[1]}
        circ = self._detect_circle(curves)
        if circ is not None:
            return {"type": "circle", "diameter": circ}
        return None

    def _detect_rectangle(self, curves: list) -> tuple[float, float] | None:
        if len(curves) != 4:
            return None
        for c in curves:
            if c.get("type") != "line":
                return None
        # collect all x and y coords
        xs: set[float] = set()
        ys: set[float] = set()
        for c in curves:
            for pt_key in ("start", "end"):
                pt = c[pt_key]
                xs.add(round(pt[0], 6))
                ys.add(round(pt[1], 6))
        if len(xs) != 2 or len(ys) != 2:
            return None
        sorted_x = sorted(xs)
        sorted_y = sorted(ys)
        width = round((sorted_x[1] - sorted_x[0]) * self.scale, 1)
        height = round((sorted_y[1] - sorted_y[0]) * self.scale, 1)
        if width <= 0 or height <= 0:
            return None
        return (width, height)

    def _detect_circle(self, curves: list) -> float | None:
        if len(curves) != 1:
            return None
        c = curves[0]
        if c.get("type") not in ("circle", "arc"):
            return None
        if c.get("type") == "circle":
            radius = c.get("radius", 0)
            return round(radius * 2 * self.scale, 1)
        # full arc (360°)
        if c.get("type") == "arc":
            # check if it's a full circle arc
            start = c.get("start", [0, 0])
            end = c.get("end", [0, 0])
            if abs(start[0] - end[0]) < 1e-6 and abs(start[1] - end[1]) < 1e-6:
                mid = c.get("mid", None)
                if mid is not None:
                    cx_approx = (start[0] + mid[0]) / 2
                    cy_approx = (start[1] + mid[1]) / 2
                    radius = math.sqrt(
                        (start[0] - cx_approx) ** 2 + (start[1] - cy_approx) ** 2
                    )
                    return round(radius * 2 * self.scale, 1)
        return None

    def _classify_plane(self, plane_data: dict) -> str | None:
        nx = plane_data.get("nx", 0)
        ny = plane_data.get("ny", 0)
        nz = plane_data.get("nz", 0)
        if abs(nz) > 0.9 and abs(nx) < 0.1 and abs(ny) < 0.1:
            return "XY"
        if abs(ny) > 0.9 and abs(nx) < 0.1 and abs(nz) < 0.1:
            return "XZ"
        if abs(nx) > 0.9 and abs(ny) < 0.1 and abs(nz) < 0.1:
            return "YZ"
        return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _pair_sketch_extrude(
        self, sequence: list[dict],
    ) -> list[tuple[dict, dict]]:
        pairs = []
        i = 0
        while i < len(sequence) - 1:
            if sequence[i].get("type") == "sketch" and sequence[i + 1].get("type") == "extrude":
                pairs.append((sequence[i], sequence[i + 1]))
                i += 2
            else:
                i += 1
        return pairs

    def _loop_center(self, curves: list) -> tuple[float, float]:
        xs, ys = [], []
        for c in curves:
            if "start" in c:
                xs.append(c["start"][0])
                ys.append(c["start"][1])
            if "end" in c:
                xs.append(c["end"][0])
                ys.append(c["end"][1])
            if "center" in c:
                return (c["center"][0], c["center"][1])
        if xs and ys:
            return (sum(xs) / len(xs), sum(ys) / len(ys))
        return (0.0, 0.0)

    # ------------------------------------------------------------------
    # code generation
    # ------------------------------------------------------------------
    def _generate_ofl_code(
        self,
        base: dict,
        holes: list[dict],
        skipped_cuts: int,
        skipped_joins: int,
        model_id: str,
    ) -> str:
        lines = ['from orionflow_ofl import *', '']

        profile = base["profile"]
        ptype = profile["type"]

        # parameters
        if ptype == "rect":
            lines.append(f'width = {profile["width"]}')
            lines.append(f'height = {profile["height"]}')
        elif ptype == "circle":
            lines.append(f'diameter = {profile["diameter"]}')
        lines.append(f'thickness = {base["thickness"]}')
        lines.append('')

        # base shape
        plane = base["plane"]
        if ptype == "rect":
            lines.append(f'part = (')
            lines.append(f'    Sketch(Plane.{plane})')
            lines.append(f'    .rect(width, height)')
            lines.append(f'    .extrude(thickness)')
            lines.append(f')')
        elif ptype == "circle":
            lines.append(f'part = (')
            lines.append(f'    Sketch(Plane.{plane})')
            lines.append(f'    .circle(diameter)')
            lines.append(f'    .extrude(thickness)')
            lines.append(f')')

        # group holes by diameter and through/depth
        if holes:
            lines.append('')
            hole_groups = self._group_holes(holes)
            for idx, group in enumerate(hole_groups):
                dia = group["diameter"]
                h_label = f"hole_{idx + 1}"
                lines.append(f'part -= (')
                lines.append(f'    Hole({dia})')
                for pos in group["positions"]:
                    lines.append(f'    .at({pos[0]}, {pos[1]})')
                if group["through"]:
                    lines.append(f'    .through()')
                else:
                    lines.append(f'    .to_depth({group["depth"]})')
                lines.append(f'    .label("{h_label}")')
                lines.append(f')')
                lines.append('')

        # skip notes
        if skipped_cuts > 0:
            lines.append(f'# NOTE: skipped {skipped_cuts} side-face cuts')
        if skipped_joins > 0:
            lines.append(f'# NOTE: skipped {skipped_joins} join operations')

        lines.append(f'export(part, "{model_id}.step")')
        return '\n'.join(lines)

    def _group_holes(self, holes: list[dict]) -> list[dict]:
        groups: list[dict] = []
        for h in holes:
            matched = False
            for g in groups:
                if (
                    g["diameter"] == h["diameter"]
                    and g["through"] == h["through"]
                    and (h["through"] or g["depth"] == h["depth"])
                ):
                    g["positions"].append((h["x"], h["y"]))
                    matched = True
                    break
            if not matched:
                groups.append(
                    {
                        "diameter": h["diameter"],
                        "through": h["through"],
                        "depth": h.get("depth"),
                        "positions": [(h["x"], h["y"])],
                    }
                )
        return groups
