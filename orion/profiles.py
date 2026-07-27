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


def involute_gear(module, teeth, bore_r, pressure_angle=20.0,
                  addendum_coef=1.0, dedendum_coef=1.25, flank_pts=8,
                  cx=0.0, cy=0.0):
    """Standard involute spur-gear profile, minus a central bore.

    Geometry follows ISO 53 / DIN 867 basic rack proportions::

        pitch radius     rp = module * teeth / 2
        base radius      rb = rp * cos(alpha)
        tip radius       ra = rp + addendum_coef * module
        root radius      rf = rp - dedendum_coef * module

    The flank is the involute of the base circle. At radius r the pressure
    angle is ``beta = acos(rb / r)`` and the involute function is
    ``inv(beta) = tan(beta) - beta``; the angular half-thickness of a tooth is

        psi(r) = pi / (2 * teeth) + inv(alpha) - inv(beta_r)

    which is the standard result and is what makes the flanks conjugate.

    **Why the area is exact rather than approximate.** The flank is emitted as
    a polyline, and that polyline *is* the geometry FreeCAD builds — the sketch
    contains exactly these segments. Shoelace over those vertices is therefore
    the exact area of the solid that gets made, not a discretisation of some
    other ideal shape. Raising ``flank_pts`` makes the gear a better involute;
    it does not make the verification more correct, because prediction and
    geometry are the same polygon by construction.
    """
    _require(module > 0, f"module must be > 0, got {module}")
    # Blueprint.resolve() evaluates every argument to a float, so counts arrive
    # as 20.0 / 5.0 and must be coerced before they index anything.
    teeth = int(round(teeth))
    flank_pts = max(3, int(round(flank_pts)))
    _require(teeth >= 6, f"teeth must be >= 6, got {teeth}")
    _require(0 < pressure_angle < 45, "pressure_angle out of range")
    alpha = math.radians(pressure_angle)
    rp = module * teeth / 2.0
    rb = rp * math.cos(alpha)
    ra = rp + addendum_coef * module
    rf = rp - dedendum_coef * module
    _require(rf > bore_r > 0,
             f"bore_r must satisfy 0 < bore_r < root radius {rf:.3f}")
    _require(ra > rb, "tip radius must exceed base radius")

    def inv(b: float) -> float:
        return math.tan(b) - b

    inv_a = inv(alpha)
    half = math.pi / (2.0 * teeth)          # angular half-thickness at pitch

    def psi(r: float) -> float:
        """Angular half-thickness of the tooth at radius r."""
        b = math.acos(max(-1.0, min(1.0, rb / r)))
        return half + inv_a - inv(b)

    # Flank sample radii: the involute exists only at or above the base circle.
    r_start = max(rb, rf)
    radii = [r_start + (ra - r_start) * i / (flank_pts - 1)
             for i in range(flank_pts)]

    pts: list[tuple[float, float]] = []
    pitch = 2.0 * math.pi / teeth
    for k in range(teeth):
        centre = k * pitch                  # tooth centreline angle
        # Below the base circle there is no involute; a radial flank down to
        # the root is the conventional substitute and is what gets cut.
        if rf < rb:
            a0 = centre - psi(rb)
            pts.append((cx + rf * math.cos(a0), cy + rf * math.sin(a0)))
        # rising flank (root -> tip) on the -psi side
        for r in radii:
            a = centre - psi(r)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        # Tip land: without a point on the tooth centreline the tip is a chord
        # between the two flank ends, so the polygon's outer radius falls short
        # of ra everywhere except at those ends — which both understates the
        # tooth and breaks any tip-diameter assertion.
        pts.append((cx + ra * math.cos(centre), cy + ra * math.sin(centre)))
        # falling flank (tip -> root) on the +psi side
        for r in reversed(radii):
            a = centre + psi(r)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        if rf < rb:
            a1 = centre + psi(rb)
            pts.append((cx + rf * math.cos(a1), cy + rf * math.sin(a1)))
        # root land across to the next tooth
        nxt = (k + 1) * pitch
        a_end = nxt - (psi(rb) if rf < rb else psi(r_start))
        a_beg = centre + (psi(rb) if rf < rb else psi(r_start))
        for j in range(1, 3):
            a = a_beg + (a_end - a_beg) * j / 3.0
            pts.append((cx + rf * math.cos(a), cy + rf * math.sin(a)))

    outer = polyline(pts)
    geo = list(outer["geometry"])
    area = outer["area"] - math.pi * bore_r * bore_r
    _require(area > 0, "bore consumed the gear body")
    geo.append(_circle(len(geo), cx, cy, bore_r))
    # The gear polygon and the bore are both centred on (cx, cy), so the
    # centroid is unchanged by the subtraction.
    return {"geometry": geo, "area": area, "centroid": (cx, cy), "loops": 2}


BUILDERS = {
    "involute_gear": involute_gear,
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
