"""Registered sketch-profile builders: geometry + EXACT analytic properties.

Blueprints never contain raw sketch coordinates. They name a builder and give
it variable-derived arguments; the builder emits both the FeatureGraph sketch
geometry (fcstd_parser vocabulary, compilable by freecad/reconstruct.py) and
the closed-form area/centroid the Tier-1 verifier predicts with. One source,
two consumers — the geometry and the math can never drift apart.

Every builder returns::

    {"geometry": [...],        # reconstruct.py-ready, XY sketch coords, mm
     "area": float,            # exact material area of the profile (mm^2)
     "centroid": (x, y),       # exact area centroid (for Pappus)
     "loops": int}

Areas are signed-composition exact — no polygonal approximation anywhere.
"""

from __future__ import annotations

import math

__all__ = ["build", "BUILDERS", "ProfileError"]


class ProfileError(ValueError):
    """Bad builder name or geometrically impossible arguments."""


def _line(i, sx, sy, ex, ey):
    return {"index": i, "construction": False, "type": "LineSegment",
            "sx": sx, "sy": sy, "ex": ex, "ey": ey}


def _circle(i, cx, cy, r):
    return {"index": i, "construction": False, "type": "Circle",
            "cx": cx, "cy": cy, "radius": r}


def _arc(i, cx, cy, r, first, last):
    return {"index": i, "construction": False, "type": "ArcOfCircle",
            "cx": cx, "cy": cy, "radius": r, "first": first, "last": last}


def _require(cond, msg):
    if not cond:
        raise ProfileError(msg)


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def circle(r, cx=0.0, cy=0.0):
    _require(r > 0, f"circle needs r > 0, got {r}")
    return {"geometry": [_circle(0, cx, cy, r)],
            "area": math.pi * r * r, "centroid": (cx, cy), "loops": 1}


def annulus(r_outer, r_inner, cx=0.0, cy=0.0):
    _require(r_outer > r_inner > 0,
             f"annulus needs r_outer > r_inner > 0, got {r_outer}, {r_inner}")
    return {"geometry": [_circle(0, cx, cy, r_outer), _circle(1, cx, cy, r_inner)],
            "area": math.pi * (r_outer ** 2 - r_inner ** 2),
            "centroid": (cx, cy), "loops": 2}


def rect(w, h, cx=0.0, cy=0.0):
    _require(w > 0 and h > 0, f"rect needs w,h > 0, got {w}, {h}")
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - h / 2, cy + h / 2
    return {"geometry": [_line(0, x0, y0, x1, y0), _line(1, x1, y0, x1, y1),
                         _line(2, x1, y1, x0, y1), _line(3, x0, y1, x0, y0)],
            "area": w * h, "centroid": (cx, cy), "loops": 1}


def rect_with_holes(w, h, holes, cx=0.0, cy=0.0):
    """Rectangle minus circular holes. holes = [(hx, hy, r), ...] absolute."""
    base = rect(w, h, cx, cy)
    geo = list(base["geometry"])
    area = base["area"]
    mx = base["centroid"][0] * area
    my = base["centroid"][1] * area
    for hx, hy, r in holes:
        _require(r > 0, f"hole needs r > 0, got {r}")
        _require(abs(hx - cx) + r < w / 2 + 1e-9 and abs(hy - cy) + r < h / 2 + 1e-9,
                 f"hole at ({hx},{hy}) r={r} leaves the rectangle")
        geo.append(_circle(len(geo), hx, hy, r))
        a = math.pi * r * r
        area -= a
        mx -= hx * a
        my -= hy * a
    _require(area > 0, "holes consumed the whole rectangle")
    return {"geometry": geo, "area": area,
            "centroid": (mx / area, my / area), "loops": 1 + len(holes)}


def rounded_rect(w, h, r, cx=0.0, cy=0.0):
    """Rectangle with four corner fillets of radius r (RectangleRounded)."""
    _require(w > 0 and h > 0, f"rounded_rect needs w,h > 0, got {w}, {h}")
    _require(0 < r < min(w, h) / 2,
             f"corner radius {r} must be < min(w,h)/2 = {min(w, h) / 2}")
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - h / 2, cy + h / 2
    g = [
        _line(0, x0 + r, y0, x1 - r, y0),
        _arc(1, x1 - r, y0 + r, r, -math.pi / 2, 0.0),
        _line(2, x1, y0 + r, x1, y1 - r),
        _arc(3, x1 - r, y1 - r, r, 0.0, math.pi / 2),
        _line(4, x1 - r, y1, x0 + r, y1),
        _arc(5, x0 + r, y1 - r, r, math.pi / 2, math.pi),
        _line(6, x0, y1 - r, x0, y0 + r),
        _arc(7, x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2),
    ]
    # Exact: full rect minus the four corner squares' non-quarter-circle rests.
    area = w * h - (4 - math.pi) * r * r
    return {"geometry": g, "area": area, "centroid": (cx, cy), "loops": 1}


def slot(length, r, cx=0.0, cy=0.0):
    """Stadium: straight length between two semicircle caps, along X."""
    _require(length > 0 and r > 0, f"slot needs length,r > 0, got {length}, {r}")
    hx = length / 2
    g = [
        _line(0, cx - hx, cy - r, cx + hx, cy - r),
        _arc(1, cx + hx, cy, r, -math.pi / 2, math.pi / 2),
        _line(2, cx + hx, cy + r, cx - hx, cy + r),
        _arc(3, cx - hx, cy, r, math.pi / 2, 3 * math.pi / 2),
    ]
    return {"geometry": g, "area": length * 2 * r + math.pi * r * r,
            "centroid": (cx, cy), "loops": 1}


def bolt_circle(n, r_bc, r_hole, cx=0.0, cy=0.0, start_deg=0.0):
    """n equal holes on a bolt circle — the profile for a patterned drilling
    done as ONE sketch. Area is the total material the tool removes."""
    n = int(round(n))
    _require(n >= 1, f"bolt_circle needs n >= 1, got {n}")
    _require(r_bc > 0 and r_hole > 0, "bolt_circle needs positive radii")
    _require(2 * r_bc * math.sin(math.pi / max(n, 2)) > 2 * r_hole or n == 1,
             f"{n} holes of r={r_hole} overlap on bolt circle r={r_bc}")
    g = []
    for i in range(n):
        a = math.radians(start_deg) + 2 * math.pi * i / n
        g.append(_circle(i, cx + r_bc * math.cos(a), cy + r_bc * math.sin(a), r_hole))
    # Centroid of the hole set: exactly the bolt-circle centre for n >= 2.
    if n == 1:
        a = math.radians(start_deg)
        c = (cx + r_bc * math.cos(a), cy + r_bc * math.sin(a))
    else:
        c = (cx, cy)
    return {"geometry": g, "area": n * math.pi * r_hole ** 2,
            "centroid": c, "loops": n}


def regular_polygon(n, r_circum, cx=0.0, cy=0.0, start_deg=0.0):
    n = int(round(n))
    _require(n >= 3, f"polygon needs n >= 3, got {n}")
    _require(r_circum > 0, "polygon needs r_circum > 0")
    pts = []
    for i in range(n):
        a = math.radians(start_deg) + 2 * math.pi * i / n
        pts.append((cx + r_circum * math.cos(a), cy + r_circum * math.sin(a)))
    g = [_line(i, pts[i][0], pts[i][1], pts[(i + 1) % n][0], pts[(i + 1) % n][1])
         for i in range(n)]
    return {"geometry": g,
            "area": 0.5 * n * r_circum ** 2 * math.sin(2 * math.pi / n),
            "centroid": (cx, cy), "loops": 1}


def polyline(points):
    """Closed polygon from explicit (x, y) points, CCW. The escape hatch for
    revolution half-profiles; area/centroid by the exact shoelace formulas."""
    _require(len(points) >= 3, "polyline needs >= 3 points")
    pts = [(float(x), float(y)) for x, y in points]
    a2 = 0.0
    mx = my = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cross = x0 * y1 - x1 * y0
        a2 += cross
        mx += (x0 + x1) * cross
        my += (y0 + y1) * cross
    _require(abs(a2) > 1e-12, "degenerate polygon")
    area = a2 / 2.0
    cx, cy = mx / (3 * a2), my / (3 * a2)
    g = [_line(i, pts[i][0], pts[i][1], pts[(i + 1) % len(pts)][0],
               pts[(i + 1) % len(pts)][1]) for i in range(len(pts))]
    return {"geometry": g, "area": abs(area), "centroid": (cx, cy), "loops": 1}


def poly_with_holes(points, holes):
    """Closed polygon (CCW points) minus circular holes — exact area/centroid
    by shoelace for the outer loop and analytic circles for the holes.
    ``holes`` = [(hx, hy, r), ...] absolute coordinates."""
    outer = polyline(points)
    geo = list(outer["geometry"])
    area = outer["area"]
    mx = outer["centroid"][0] * area
    my = outer["centroid"][1] * area
    for hx, hy, r in holes:
        _require(r > 0, f"hole needs r > 0, got {r}")
        geo.append(_circle(len(geo), hx, hy, r))
        a = math.pi * r * r
        area -= a
        mx -= hx * a
        my -= hy * a
    _require(area > 0, "holes consumed the polygon")
    return {"geometry": geo, "area": area,
            "centroid": (mx / area, my / area), "loops": 1 + len(holes)}


def hole_grid(w, h, nx, ny, r, pitch_x, pitch_y, cx=0.0, cy=0.0):
    """Rectangle with an nx*ny grid of circular holes — one exact profile.
    The grid is centred in the rectangle; area is exact (holes are disjoint by
    the caller's pitch guard)."""
    _require(w > 0 and h > 0, "hole_grid needs w,h > 0")
    nx, ny = int(round(nx)), int(round(ny))
    _require(nx >= 1 and ny >= 1, "hole_grid needs nx,ny >= 1")
    base = rect(w, h, cx, cy)
    geo = list(base["geometry"])
    area = base["area"]
    gx0 = cx - pitch_x * (nx - 1) / 2.0
    gy0 = cy - pitch_y * (ny - 1) / 2.0
    n = 0
    for ix in range(nx):
        for iy in range(ny):
            hx = gx0 + ix * pitch_x
            hy = gy0 + iy * pitch_y
            _require(abs(hx - cx) + r < w / 2 + 1e-9
                     and abs(hy - cy) + r < h / 2 + 1e-9,
                     "grid hole leaves the plate")
            geo.append(_circle(len(geo), hx, hy, r))
            n += 1
    area -= n * math.pi * r * r
    _require(area > 0, "grid holes consumed the plate")
    return {"geometry": geo, "area": area, "centroid": (cx, cy),
            "loops": 1 + n}


def arc_spine(radius, sweep_deg, cx=0.0, cy=0.0):
    """OPEN circular-arc path for a Sweep spine — starts at the origin heading
    +X, curving toward +Y. Not a closed profile: area is 0 by definition and
    the sweep predictor consumes ``radius``/``sweep_deg`` directly."""
    _require(radius > 0, "arc_spine needs radius > 0")
    _require(0 < sweep_deg <= 360, f"sweep_deg {sweep_deg} out of range")
    a0 = -math.pi / 2
    a1 = a0 + math.radians(sweep_deg)
    return {"geometry": [_arc(0, cx, cy + radius, radius, a0, a1)],
            "area": 0.0, "centroid": (cx, cy), "loops": 0}


BUILDERS = {
    "circle": circle,
    "arc_spine": arc_spine,
    "poly_with_holes": poly_with_holes,
    "hole_grid": hole_grid,
    "annulus": annulus,
    "rect": rect,
    "rect_with_holes": rect_with_holes,
    "rounded_rect": rounded_rect,
    "slot": slot,
    "bolt_circle": bolt_circle,
    "regular_polygon": regular_polygon,
    "polyline": polyline,
}


def build(name: str, **kwargs):
    if name not in BUILDERS:
        raise ProfileError(f"unknown profile builder {name!r}; "
                           f"have {sorted(BUILDERS)}")
    return BUILDERS[name](**kwargs)
