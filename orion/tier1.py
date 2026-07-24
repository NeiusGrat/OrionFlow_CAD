"""Tier-1 closed-form predictions, independent of FreeCAD.

Two modes share the same formulas:

* **Blueprint mode** — the profile builder supplies exact area/centroid and
  these functions predict feature tool volumes ahead of any build.
* **Graph-analytic mode** — for parts with no blueprint (the 100 gNucleus
  masters), :func:`sketch_area` recovers exact area/centroid from extracted
  sketch geometry via Green's theorem, and the same predictors run per feature
  against the measured PartDesign ``AddSubShape`` (the boolean-free tool
  solid). That per-feature comparison is precisely what catches the class of
  bug where a feature builds clean but half-sized (SideType/Length2).

Everything here is pure math; if a precondition for exactness fails the
function returns ``None`` with a reason rather than an approximate number.
"""

from __future__ import annotations

import math

_TOL = 1e-7


# --------------------------------------------------------------------------- #
# Green's theorem over extracted sketch geometry
# --------------------------------------------------------------------------- #
def _arc_endpoints(g):
    cx, cy, r = g["cx"], g["cy"], g["radius"]
    a0, a1 = g["first"], g["last"]
    return ((cx + r * math.cos(a0), cy + r * math.sin(a0)),
            (cx + r * math.cos(a1), cy + r * math.sin(a1)))


def _seg_area(g, reverse):
    """Signed contribution of one traversed segment to ½∮(x dy − y dx)."""
    if g["type"] == "LineSegment":
        (xa, ya), (xb, yb) = (g["sx"], g["sy"]), (g["ex"], g["ey"])
        if reverse:
            (xa, ya), (xb, yb) = (xb, yb), (xa, ya)
        return 0.5 * (xa * yb - xb * ya)
    # ArcOfCircle: ½[r²Δθ + cx(yb−ya) − cy(xb−xa)], Δθ signed by traversal.
    (xa, ya), (xb, yb) = _arc_endpoints(g)
    dth = g["last"] - g["first"]
    if reverse:
        (xa, ya), (xb, yb) = (xb, yb), (xa, ya)
        dth = -dth
    return 0.5 * (g["radius"] ** 2 * dth
                  + g["cx"] * (yb - ya) - g["cy"] * (xb - xa))


def _seg_moments(g, reverse, steps=0):
    """(∫x dA, ∫y dA) contribution — exact for lines and arcs.

    Line:  Mx = (1/6)(xa+xb)(xa*yb−xb*ya)... use the standard shoelace moment.
    Arc:   centroid moments from the circular-sector decomposition.
    """
    if g["type"] == "LineSegment":
        (xa, ya), (xb, yb) = (g["sx"], g["sy"]), (g["ex"], g["ey"])
        if reverse:
            (xa, ya), (xb, yb) = (xb, yb), (xa, ya)
        cross = xa * yb - xb * ya
        return ((xa + xb) * cross / 6.0, (ya + yb) * cross / 6.0)
    (xa, ya), (xb, yb) = _arc_endpoints(g)
    a0, a1 = g["first"], g["last"]
    if reverse:
        (xa, ya), (xb, yb) = (xb, yb), (xa, ya)
        a0, a1 = a1, a0
    cx, cy, r = g["cx"], g["cy"], g["radius"]
    dth = a1 - a0
    # Decompose the traversed arc region (relative to origin) as: triangle
    # (0, A, B) with A/B the endpoints, plus circular segment beyond chord.
    # Work instead with exact integrals: parametrize and integrate
    #   Mx = ∫ x · ½(x dy − y dx) is messy; use sector-about-centre + shift.
    # Sector about the circle centre: area  s = ½ r² dth,
    #   centroid (relative to centre) at angle m=(a0+a1)/2, distance
    #   d = (4r/3)·sin(dth/2)/dth  (standard circular-sector centroid; for
    #   dth→0 this limits to r).
    if abs(dth) < 1e-12:
        return (0.0, 0.0)
    s = 0.5 * r * r * dth
    m = 0.5 * (a0 + a1)
    d = (4.0 * r / 3.0) * math.sin(0.5 * dth) / dth
    sec_mx = s * (cx + d * math.cos(m))
    sec_my = s * (cy + d * math.sin(m))
    # Triangle (origin, centre→A endpoint chain): the Green traversal we use
    # for area is origin-based, the sector is centre-based. Bridge with the
    # two origin-triangles (O, A, C) and (O, C, B):
    tri = 0.0
    tri_mx = tri_my = 0.0
    for (px, py), (qx, qy) in (((xa, ya), (cx, cy)), ((cx, cy), (xb, yb))):
        cr = px * qy - qx * py
        tri += 0.5 * cr
        tri_mx += (px + qx) * cr / 6.0
        tri_my += (py + qy) * cr / 6.0
    return (tri_mx + sec_mx, tri_my + sec_my)


# --------------------------------------------------------------------------- #
# B-spline boundary integration (exact for non-rational curves)
# --------------------------------------------------------------------------- #
# A planar region bounded by B-spline curves has area A = 1/2 oint (x dy-y dx).
# A non-rational degree-p B-spline is piecewise polynomial, so each Bezier span
# contributes a polynomial integrand: the area integrand x*y'-y*x' has degree
# 2p-1, the first-moment integrands x^2*y' / y^2*x' have degree 3p-1. A 5-point
# Gauss-Legendre rule is exact through degree 9, covering both for p<=3 with no
# discretisation error and no OCC dependency. Rational curves would make the
# integrand a rational function (Gauss no longer exact); those are refused.

# 5-point Gauss-Legendre nodes/weights mapped from [-1,1] to [0,1].
_GL5 = [
    (0.5 - 0.9061798459386640 / 2, 0.2369268850561891 / 2),
    (0.5 - 0.5384693101056831 / 2, 0.4786286704993665 / 2),
    (0.5, 0.5688888888888889 / 2),
    (0.5 + 0.5384693101056831 / 2, 0.4786286704993665 / 2),
    (0.5 + 0.9061798459386640 / 2, 0.2369268850561891 / 2),
]


def _lerp(a, b, t):
    return ((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1])


def _expand_knots(knots, mults):
    u = []
    for k, m in zip(knots, mults):
        u.extend([float(k)] * int(round(m)))
    return u


def _insert_knot(p, u_vec, poles, u):
    """One Boehm knot insertion at parameter ``u``. Returns (U', P')."""
    k = max(i for i in range(len(u_vec) - 1)
            if u_vec[i] <= u < u_vec[i + 1] and u_vec[i] != u_vec[i + 1])
    out = []
    for i in range(len(poles) + 1):
        if i <= k - p:
            out.append(poles[i])
        elif i <= k:
            denom = u_vec[i + p] - u_vec[i]
            a = (u - u_vec[i]) / denom if denom else 0.0
            out.append(_lerp(poles[i - 1], poles[i], a))
        else:
            out.append(poles[i - 1])
    return u_vec[:k + 1] + [u] + u_vec[k + 1:], out


def _bezier_segments(g):
    """Decompose a non-rational B-spline into degree-p Bezier segments (each a
    list of p+1 (x, y) control points) by raising every interior knot to
    multiplicity p."""
    p = int(g["degree"])
    poles = [(float(pt[0]), float(pt[1])) for pt in g["poles"]]
    knots, mults = g["knots"], [int(round(m)) for m in g["mults"]]
    u_vec = _expand_knots(knots, mults)
    for kv, m in zip(knots[1:-1], mults[1:-1]):     # interior knots only
        for _ in range(p - m):
            u_vec, poles = _insert_knot(p, u_vec, poles, float(kv))
    # After decomposition control points partition into overlapping groups of
    # p+1 sharing endpoints: [0..p], [p..2p], ...
    n_seg = (len(poles) - 1) // p
    return [poles[s * p:s * p + p + 1] for s in range(n_seg)]


def _decasteljau(ctrl, t):
    """Point and derivative of a Bezier segment at t (de Casteljau)."""
    p = len(ctrl) - 1
    pts = list(ctrl)
    for r in range(1, p):
        pts = [_lerp(pts[i], pts[i + 1], t) for i in range(len(pts) - 1)]
    # pts now has 2 points (level p-1); derivative = p*(pts[1]-pts[0])
    dx = p * (pts[1][0] - pts[0][0])
    dy = p * (pts[1][1] - pts[0][1])
    point = _lerp(pts[0], pts[1], t)
    return point[0], point[1], dx, dy


def _bspline_contribution(g, reverse):
    """(area, mx, my) contribution of one B-spline edge to the boundary
    integrals, traversed start->end (negated if ``reverse``)."""
    a = mx = my = 0.0
    for seg in _bezier_segments(g):
        for t, w in _GL5:
            x, y, dx, dy = _decasteljau(seg, t)
            a += w * 0.5 * (x * dy - y * dx)
            mx += w * 0.5 * (x * x * dy)
            my += w * -0.5 * (y * y * dx)
    return (-a, -mx, -my) if reverse else (a, mx, my)


def _bspline_endpoints(g):
    poles = g["poles"]
    return ((float(poles[0][0]), float(poles[0][1])),
            (float(poles[-1][0]), float(poles[-1][1])))


def _bspline_polyline(g, reverse, n=24):
    segs = _bezier_segments(g)
    pts = []
    for seg in segs:
        for k in range(n):
            x, y, _dx, _dy = _decasteljau(seg, k / n)
            pts.append((x, y))
    return list(reversed(pts)) if reverse else pts


def sketch_area(geometry, external=()):
    """Exact (area, centroid) of an extracted sketch's material region.

    Returns (area, (cx, cy), None) on success or (None, None, reason).
    Supports Circle / LineSegment / ArcOfCircle and non-rational B-splines
    (exact via Bezier + Gauss). Rational B-splines, ellipses and points are
    refused rather than approximated.
    """
    live = [g for g in list(geometry) + list(external)
            if not g.get("construction")]
    if not live:
        return None, None, "no geometry"
    for g in live:
        t = g.get("type")
        if t not in ("Circle", "LineSegment", "ArcOfCircle", "BSpline"):
            return None, None, f"unsupported geometry {t}"
        if t == "BSpline" and g.get("rational"):
            return None, None, "rational B-spline (Gauss not exact)"

    circles = [g for g in live if g["type"] == "Circle"]
    segs = [g for g in live if g["type"] != "Circle"]

    loops = []  # (area, mx, my, outline) — outline is for containment tests
    for c in circles:
        a = math.pi * c["radius"] ** 2
        loops.append((a, a * c["cx"], a * c["cy"],
                      ("circle", (c["cx"], c["cy"], c["radius"]))))

    # Chain open segments into closed loops by endpoint proximity.
    def endpoints(g):
        if g["type"] == "LineSegment":
            return (g["sx"], g["sy"]), (g["ex"], g["ey"])
        if g["type"] == "BSpline":
            return _bspline_endpoints(g)
        return _arc_endpoints(g)

    def seg_contribution(g, reverse):
        if g["type"] == "BSpline":
            return _bspline_contribution(g, reverse)
        return (_seg_area(g, reverse),) + _seg_moments(g, reverse)

    unused = list(range(len(segs)))
    tol = 1e-5
    while unused:
        i = unused.pop(0)
        chain = [(i, False)]
        start, cur = endpoints(segs[i])
        guard = 0
        while (abs(cur[0] - start[0]) > tol or abs(cur[1] - start[1]) > tol):
            guard += 1
            if guard > len(segs) + 1:
                return None, None, "open profile (chain never closes)"
            hit = None
            for j in list(unused):
                p, q = endpoints(segs[j])
                if abs(p[0] - cur[0]) <= tol and abs(p[1] - cur[1]) <= tol:
                    hit, rev, nxt = j, False, q
                    break
                if abs(q[0] - cur[0]) <= tol and abs(q[1] - cur[1]) <= tol:
                    hit, rev, nxt = j, True, p
                    break
            if hit is None:
                return None, None, "open profile (dangling endpoint)"
            unused.remove(hit)
            chain.append((hit, rev))
            cur = nxt
        a = mx = my = 0.0
        for j, rev in chain:
            da, dmx, dmy = seg_contribution(segs[j], rev)
            a += da
            mx += dmx
            my += dmy
        if a < 0:  # normalize loop orientation; sign conveys nothing here
            a, mx, my = -a, -mx, -my
        # Polyline outline (arcs sampled) — used ONLY for containment tests,
        # never for area, so exactness is preserved.
        pts = []
        for j, rev in chain:
            g = segs[j]
            if g["type"] == "LineSegment":
                p = (g["ex"], g["ey"]) if rev else (g["sx"], g["sy"])
                pts.append(p)
            elif g["type"] == "BSpline":
                pts.extend(_bspline_polyline(g, rev))
            else:
                a0, a1 = g["first"], g["last"]
                if rev:
                    a0, a1 = a1, a0
                for k in range(16):
                    t = a0 + (a1 - a0) * k / 16.0
                    pts.append((g["cx"] + g["radius"] * math.cos(t),
                                g["cy"] + g["radius"] * math.sin(t)))
        loops.append((a, mx, my, ("poly", pts)))

    if not loops:
        return None, None, "no closed loops"

    def contains(outline, pt) -> bool:
        kind, data = outline
        if kind == "circle":
            cx, cy, r = data
            return math.hypot(pt[0] - cx, pt[1] - cy) < r
        # ray cast to +x over the polyline
        inside = False
        pts = data
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            if (y0 > pt[1]) != (y1 > pt[1]):
                xin = x0 + (pt[1] - y0) * (x1 - x0) / (y1 - y0)
                if xin > pt[0]:
                    inside = not inside
        return inside

    # Even-odd forest: a loop's nesting DEPTH decides its sign. Depth 0 =
    # material, depth 1 = hole, depth 2 = island in a hole, and so on. This
    # is the rule that gets all three real cases right at once: concentric
    # annulus stacks (three counterbore rings in one sketch), disjoint
    # sibling loops (a bolt circle), and plain outer-plus-holes.
    def boundary_point(outline):
        # A point ON the loop, not its centroid: concentric loops share a
        # centroid, so centroid-based depth counts poison each other.
        kind, data = outline
        if kind == "circle":
            cx, cy, r = data
            return (cx + r, cy)
        return data[0]

    area = mx = my = 0.0
    for i, (a, lmx, lmy, own) in enumerate(loops):
        rep = boundary_point(own)
        depth = sum(1 for j, (_a, _x, _y, outl) in enumerate(loops)
                    if j != i and contains(outl, rep))
        sign = 1.0 if depth % 2 == 0 else -1.0
        area += sign * a
        mx += sign * lmx
        my += sign * lmy
    if area <= _TOL:
        return None, None, "holes consume the outer loop"
    return area, (mx / area, my / area), None


# --------------------------------------------------------------------------- #
# feature tool-volume predictors
# --------------------------------------------------------------------------- #
def extrusion_volume(area, params):
    """Exact tool volume of a Pad/Pocket. Returns (volume, None) or (None, why).

    The SideType/Length2 rule this encodes is the exact bug class found on
    2026-07-22: 'Two sides' carries material on BOTH Length and Length2, and a
    build that ignores Length2 recomputes clean at half the volume.
    """
    if area is None or area <= 0:
        return None, "no analytic profile area"
    if params.get("Type", "Length") != "Length":
        return None, f"Type={params.get('Type')!r} is not closed-form"
    taper = float(params.get("TaperAngle", 0.0) or 0.0)
    taper2 = float(params.get("TaperAngle2", 0.0) or 0.0)
    if abs(taper) > _TOL or abs(taper2) > _TOL:
        return None, "tapered extrusion is Tier 2"
    length = float(params.get("Length", 0.0) or 0.0)
    if length <= 0:
        return None, "Length <= 0"
    side = params.get("SideType")
    if side is None:
        side = "Two sides" if params.get("Midplane") else "One side"
    if side == "One side":
        return area * length, None
    if side == "Symmetric":
        return area * length, None       # total length split half/half
    if side == "Two sides":
        if params.get("Type2", "Length") != "Length":
            return None, f"Type2={params.get('Type2')!r} is not closed-form"
        length2 = float(params.get("Length2", 0.0) or 0.0)
        return area * (length + length2), None
    return None, f"unknown SideType {side!r}"


def revolution_volume(area, centroid, axis_2d, params):
    """Pappus: V = A · θ · R̄ with R̄ the centroid's distance from the axis.

    ``axis_2d`` is ((px, py), (dx, dy)) in SKETCH coordinates. Refuses when
    the axis cuts the profile (Pappus needs the region on one side).
    """
    if area is None or area <= 0:
        return None, "no analytic profile area"
    angle = float(params.get("Angle", 360.0) or 360.0)
    if not 0 < angle <= 360.0 + 1e-9:
        return None, f"angle {angle} out of range"
    (px, py), (dx, dy) = axis_2d
    n = math.hypot(dx, dy)
    if n < 1e-12:
        return None, "degenerate axis"
    r_bar = abs((centroid[0] - px) * (dy / n) - (centroid[1] - py) * (dx / n))
    if r_bar < _TOL:
        return None, "profile centroid on the axis"
    return area * math.radians(angle) * r_bar, None


def pattern_volume(base_volume, occurrences):
    """N·V for a transform pattern — exact ONLY when instances are disjoint;
    the caller is responsible for the non-overlap precondition."""
    n = int(occurrences)
    if n < 1 or base_volume is None:
        return None, "bad pattern inputs"
    return base_volume * n, None


def mirror_volume(base_volume):
    """2·V — exact only when the base does not straddle the mirror plane."""
    if base_volume is None:
        return None, "no base volume"
    return 2.0 * base_volume, None


def chamfer_ring_volume(edge_radius, size):
    """Material removed by a 45° chamfer on a circular edge of radius R:
    right-triangle section (legs = size) revolved at its centroid radius.
    Exact Pappus; centroid of the triangle sits at R − size/3 for an outer
    edge chamfer cutting inward."""
    if edge_radius <= 0 or size <= 0 or size >= edge_radius:
        return None, "bad chamfer geometry"
    a = 0.5 * size * size
    r_c = edge_radius - size / 3.0
    return a * 2.0 * math.pi * r_c, None


def fillet_ring_volume(edge_radius, r):
    """Material removed by radius-r fillet on a circular convex edge R:
    section area r²(1 − π/4), centroid offset from the edge by the exact
    quarter-circle-complement centroid  e = r·(10 − 3π)/(12 − 3π)."""
    if edge_radius <= 0 or r <= 0 or r >= edge_radius:
        return None, "bad fillet geometry"
    a = r * r * (1.0 - math.pi / 4.0)
    e = r * (10.0 - 3.0 * math.pi) / (12.0 - 3.0 * math.pi)
    return a * 2.0 * math.pi * (edge_radius - e), None


def chamfer_hole_rim_volume(r_hole, size):
    """45° chamfer on a hole rim (concave edge): the triangular section sits
    OUTWARD from the wall, centroid at r_hole + size/3. Exact Pappus."""
    if r_hole <= 0 or size <= 0:
        return None, "bad chamfer geometry"
    return 0.5 * size * size * 2.0 * math.pi * (r_hole + size / 3.0), None


def fillet_hole_rim_volume(r_hole, r):
    """Radius-r fillet on a hole rim: section r²(1−π/4) with centroid offset
    e = r(10−3π)/(12−3π) measured outward from the hole wall."""
    if r_hole <= 0 or r <= 0:
        return None, "bad fillet geometry"
    a = r * r * (1.0 - math.pi / 4.0)
    e = r * (10.0 - 3.0 * math.pi) / (12.0 - 3.0 * math.pi)
    return a * 2.0 * math.pi * (r_hole + e), None


def straight_chamfer_volume(edge_length, size):
    """45° chamfer on an isolated straight edge. The caller must guarantee the
    edge set is disjoint (no shared vertices) — corner interaction volumes are
    NOT included, by design."""
    if edge_length <= 0 or size <= 0:
        return None, "bad chamfer geometry"
    return 0.5 * size * size * edge_length, None


def straight_fillet_volume(edge_length, r):
    """Radius-r fillet on an isolated straight 90° edge; same disjointness
    contract as straight_chamfer_volume."""
    if edge_length <= 0 or r <= 0:
        return None, "bad fillet geometry"
    return (1.0 - math.pi / 4.0) * r * r * edge_length, None


def frustum_volume(a1, a2, h):
    """Draft on a prismatic solid → frustum: V = h/3 (A1 + A2 + √(A1·A2))."""
    if a1 <= 0 or a2 <= 0 or h <= 0:
        return None, "bad frustum inputs"
    return h / 3.0 * (a1 + a2 + math.sqrt(a1 * a2)), None


def prismatoid_volume(a1, am, a2, h):
    """Loft between parallel sections: V = h/6 (A1 + 4·Am + A2). Exact for
    ruled lofts whose lateral faces are planes/quadrics (incl. cone frusta)."""
    if min(a1, am, a2) <= 0 or h <= 0:
        return None, "bad prismatoid inputs"
    return h / 6.0 * (a1 + 4.0 * am + a2), None


def sweep_pappus_volume(area, spine_radius, sweep_angle_deg, centroid_offset=0.0):
    """Generalized Pappus for a circular-arc spine with Frenet framing:
    V = A · θ · (R + e), e = signed in-plane centroid offset from the spine.
    Precondition (caller-checked): R − |e| > max section extent, else the
    inner side self-intersects and the formula overcounts."""
    if area <= 0 or spine_radius <= 0:
        return None, "bad sweep inputs"
    th = math.radians(sweep_angle_deg)
    if not 0 < th <= 2 * math.pi + 1e-9:
        return None, "bad sweep angle"
    r_eff = spine_radius + centroid_offset
    if r_eff <= 0:
        return None, "centroid crosses the spine centre"
    return area * th * r_eff, None
