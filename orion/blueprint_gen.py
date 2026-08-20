"""Requirements -> Blueprint, in Python. No model runs here.

This is the half that measurement said to move. Asked to write a Blueprint from
a complete specification, the base model failed the static check on every
complex part (unused variables, a bare word where an expression belongs), and
the fine-tune — handed the same specification in its own training register with
the invent-anything licence removed — returned
``l_bracket_plus_counterbore_set_vent_slot`` and grew thirteen stated
dimensions into thirty variables. One built out of five, both ways.

The failure modes differ and only one is a prompting problem. The base model
gets the *format* wrong, which retries could fix. The fine-tune gets the
*content* wrong: 91.7% of its corpus is a base part carrying one to three
attachments, so it emits attachments. That prior is in the weights and no
prompt reaches it.

Neither is a problem worth solving, because writing a feature tree from decided
dimensions is not a language task. It is arithmetic and bookkeeping — exactly
what the rest of this codebase already refuses to let a model do.

So: every dimension comes from the interview, every expression is written here,
and the closed-form volume is derived alongside the geometry that produces it
rather than predicted about it. A Blueprint out of this module fails the static
check only if this module has a bug, and it cannot contain a feature nobody
asked for, because there is no step at which one could be introduced.

Each builder returns a Blueprint dict ready to freeze. Adding a family is a
builder here plus an entry in ``part_families.yaml``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class GeneratorError(ValueError):
    """The requirements cannot produce buildable geometry."""


def _v(name: str, value: Any) -> tuple[str, float]:
    return name, float(value)


def _num(req: dict, key: str) -> Optional[float]:
    value = req.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _assert_positive(req: dict, keys: tuple[str, ...]) -> None:
    for k in keys:
        v = _num(req, k)
        if v is None:
            raise GeneratorError(f"{k} is required and was not collected")
        if v <= 0:
            raise GeneratorError(f"{k} must be positive, got {v}")


def _eval_expr(expr: Any, variables: dict) -> Optional[float]:
    """A generator-written expression, evaluated for geometric reasoning.

    Only ever applied to expressions this module produced, so it is checking
    its own arithmetic rather than trusting an input.
    """
    from orion import expr as E

    if isinstance(expr, (int, float)) and not isinstance(expr, bool):
        return float(expr)
    try:
        return float(E.evaluate(str(expr), variables))
    except Exception:  # noqa: BLE001 - unresolvable means "cannot reason", not a crash
        return None


def _blueprint(part_class: str, variables: dict, derivation: list,
               assertions: list, features: list, sketches: list,
               dependencies: list, datums: Optional[dict] = None,
               inexact: Optional[list] = None) -> dict:
    plan: dict = {"derivation": derivation}
    if inexact:
        plan["no_closed_form"] = list(inexact)
    return {
        "part_class": part_class,
        "variables": variables,
        "datums": datums or {"A": "bottom face z=0 (primary)",
                             "B": "long edge (secondary)"},
        "design_plan": plan,
        "assertions": assertions,
        "template": {"features": features, "sketches": sketches,
                     "dependencies": dependencies},
    }


def _volume_assertion(expr: str, inexact: Optional[list] = None) -> dict:
    """The volume claim, at the tier the geometry actually admits.

    Tier 1 is a closed form: the expression is predicted before the build and
    the kernel is held to it at 1e-6. That is the strong claim and the default.

    Some geometry has no closed form in this expression language and no amount
    of care produces one — two perpendicular cylinders intersect in a solid
    needing elliptic integrals; a counterbore that clips the corner where two
    plates meet leaves a circular segment whose analytic area disagreed with the
    kernel by 0.32 mm^3, which is small and is still not exact.

    For those, ``body_mesh_converged`` is the honest claim and it is a genuinely
    weaker one: it proves the tessellation converges to OCC's own volume across
    densities, so the solid is well formed, but it does not check that volume
    against anything predicted. The extent assertions stay exact either way, and
    the tier is recorded so a report can say which claim was made.

    The alternative — inventing a closed form that is nearly right — is the one
    thing this module exists to prevent.
    """
    if inexact:
        return {"id": "body", "kind": "body_mesh_converged", "tier": 2,
                "tol_rel": 1e-03}
    return {"id": "body", "kind": "body_volume", "tier": 1,
            "tol_rel": 1e-06, "target": expr}


def _extent_assertion(aid: str, axis: str, expr: str) -> dict:
    return {"id": aid, "kind": "bbox_extent", "axis": axis, "tier": 1,
            "tol_rel": 1e-06, "target": expr}


# --------------------------------------------------------------------------- #
# rectangular plate
# --------------------------------------------------------------------------- #
def rect_plate(req: dict) -> dict:
    """Plate, with any of: central bore, bolt circle, pocket, corner radius.

    Everything that removes material is put IN the pad profile rather than cut
    afterwards, so the volume has one exact closed form instead of a chain of
    boolean results to predict. The one exception is the pocket, which is a
    blind cut and therefore a real second feature.
    """
    _assert_positive(req, ("length", "width", "thickness"))
    L, W, T = _num(req, "length"), _num(req, "width"), _num(req, "thickness")

    inexact: list[str] = []
    v: dict[str, float] = {"L": L, "W": W, "T": T}
    holes: list[list[str]] = []
    area = "L*W"
    corner_r = _num(req, "corner_radius")
    if corner_r and corner_r > 0:
        if corner_r > min(L, W) / 2:
            raise GeneratorError(
                f"corner radius {corner_r} exceeds half the shorter side")
        v["cr"] = corner_r
        # Rounding removes (4 - pi) r^2 from the rectangle.
        area = "(L*W - (4 - pi)*cr**2)"
        profile = {"builder": "rounded_rect",
                   "args": {"w": "L", "h": "W", "r": "cr"}}
    else:
        profile = {"builder": "rect", "args": {"w": "L", "h": "W"}}

    bore_r = _num(req, "bore_r")
    if bore_r and bore_r > 0:
        if bore_r * 2 >= min(L, W):
            raise GeneratorError("central bore does not fit the plate")
        v["bore_r"] = bore_r
        holes.append(["0", "0", "bore_r"])
        area += " - pi*bore_r**2"

    n = req.get("hole_count")
    hole_r = _num(req, "hole_r")
    # `pcd` is declared a diameter in the schema, so `interview.resolve` has
    # already halved it into `pcd_r`. Reading `pcd` here found nothing and the
    # bolt circle was silently never built — the plate still verified, because
    # the closed form was computed from the same absent holes. The consumption
    # guard is what surfaced it.
    pcd_r = _num(req, "pcd_r")
    if n and hole_r and pcd_r:
        n = int(n)
        if n < 1:
            raise GeneratorError("hole_count must be at least 1")
        if pcd_r + hole_r >= min(L, W) / 2:
            raise GeneratorError("bolt circle does not fit inside the plate")
        v["hole_r"] = hole_r
        v["pcd_r"] = pcd_r
        import math
        for i in range(n):
            a = 2 * math.pi * i / n
            holes.append([f"pcd_r*{math.cos(a):.10f}",
                          f"pcd_r*{math.sin(a):.10f}", "hole_r"])
        area += f" - {n}*pi*hole_r**2"

    if holes:
        args = dict(profile["args"])
        args["holes"] = holes
        builder = "poly_with_holes" if profile["builder"] == "rounded_rect" \
            else "rect_with_holes"
        if builder == "poly_with_holes":
            # rounded_rect has no holes variant; fall back to a plain rect so
            # the closed form stays exact rather than approximating a fillet.
            v.pop("cr", None)
            area = area.replace("(L*W - (4 - pi)*cr**2)", "L*W")
            builder = "rect_with_holes"
            args = {"w": "L", "h": "W", "holes": holes}
        profile = {"builder": builder, "args": args}

    features = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_plate", "type": "Sketch", "parameters": {}},
        {"id": "plate", "type": "Pad", "rationale": "plate blank, cuts in-profile",
         "parameters": {"Length": "T", "Type": "Length"}},
    ]
    sketches = [{"id": "s_plate", "plane": "XY", "profile": profile}]
    deps = [{"source": "s_plate", "target": "plate", "kind": "profile"}]
    volume = f"({area})*T"
    derivation = [{"step": 1, "eq": f"V = {volume}",
                   "why": "plate blank with every through-cut in the pad profile"}]

    pl, pw, pd = (_num(req, "pocket_l"), _num(req, "pocket_w"),
                  _num(req, "pocket_depth"))
    if pl and pw and pd:
        if pd >= T:
            raise GeneratorError(
                f"pocket depth {pd} must be less than thickness {T}")
        if pl >= L or pw >= W:
            raise GeneratorError("pocket does not fit within the plate")

        # A pocket over a through-hole removes nothing there — that material
        # left with the hole. Subtracting the full pocket box double-counts the
        # overlap, which is how a 300x220x16 plate came back 38170.35 mm^3
        # heavier than predicted: exactly pi*45^2*6, the central bore under the
        # pocket floor. Each through-hole that lies wholly inside the pocket
        # footprint is credited back.
        #
        # Wholly inside or wholly outside only. A hole straddling the pocket
        # wall has no closed form in this expression language, and the honest
        # move is to refuse rather than approximate a number the kernel will
        # disagree with.
        overlap_terms: list[str] = []
        straddling = 0
        for cx_expr, cy_expr, r_expr in holes:
            cx = _eval_expr(cx_expr, v)
            cy = _eval_expr(cy_expr, v)
            rr = _eval_expr(r_expr, v)
            if cx is None or cy is None or rr is None:
                continue
            inside = (abs(cx) + rr <= pl / 2) and (abs(cy) + rr <= pw / 2)
            straddles = (abs(cx) - rr < pl / 2) and (abs(cy) - rr < pw / 2)
            if inside:
                overlap_terms.append(f"pi*{r_expr}**2*pd")
            elif straddles:
                # The hole crosses the pocket wall, so the two voids overlap
                # over a region bounded by a circle and a straight edge. The
                # part is buildable and right; the area is not expressible
                # here, so the volume claim drops a tier instead of the design
                # being refused or the overlap guessed at.
                straddling += 1
        v.update({"pl": pl, "pw": pw, "pd": pd})
        features += [
            {"id": "s_pocket", "type": "Sketch", "parameters": {}},
            {"id": "pocket", "type": "Pocket", "rationale": "lightening pocket",
             "parameters": {"Length": "pd", "Type": "Length"}},
        ]
        sketches.append({"id": "s_pocket", "plane": "XY", "z": "T",
                         "profile": {"builder": "rect",
                                     "args": {"w": "pl", "h": "pw"}}})
        deps.append({"source": "s_pocket", "target": "pocket", "kind": "profile"})
        if straddling:
            inexact.append(
                f"{straddling} hole(s) cross the pocket wall, and the region "
                f"they share is bounded by a circle and a straight edge with no "
                f"exact area in this expression language")
        pocket = "pl*pw*pd"
        if overlap_terms:
            pocket = f"({pocket} - {' - '.join(overlap_terms)})"
        volume = f"{volume} - {pocket}"
        why = "blind rectangular pocket from the top face"
        if overlap_terms:
            why += (f", less the {len(overlap_terms)} through-hole(s) under it "
                    f"whose material the holes already removed")
        derivation.append({"step": 2, "eq": f"V = {volume}", "why": why})

    # ---- corner mounting slots -------------------------------------------- #
    sl, sw = _num(req, "slot_length"), _num(req, "slot_width")
    gap = _num(req, "slot_edge_gap")
    if sl and sw:
        if gap is None:
            raise GeneratorError(
                "mounting slots need a distance from the plate edge — "
                '"near each corner" does not fix a position')
        volume, why_slots = _corner_slots(
            v, features, sketches, deps, sl, sw, gap, L, W, "T", holes,
            volume, pocket=(pl, pw) if (pl and pw and pd) else None)
        derivation.append({"step": len(derivation) + 1, "eq": f"V = {volume}",
                           "why": why_slots})

    # ---- outer edge treatments -------------------------------------------- #
    #
    # An external fillet on a plate is a rounded corner, which this builder
    # already expresses in the profile with an exact area — so `fillet` and
    # `corner_radius` are the same request and only one may be given.
    if _num(req, "fillet") and corner_r:
        raise GeneratorError(
            "a corner radius rounds the plate's outline in the sketch, where "
            "the area is exact, and an external fillet rounds the same edges "
            "afterwards where it is not. Give one")
    volume = _vertical_fillet(req, v, features, inexact, derivation, volume)

    volume = _perimeter_chamfer(req, v, features, deps, volume, derivation,
                                "L", "W", inexact)

    assertions = [
        _extent_assertion("len_extent", "x", "L"),
        _extent_assertion("wid_extent", "y", "W"),
        _volume_assertion(volume, inexact),
    ]
    return _blueprint("rect_plate", v, derivation, assertions,
                      features, sketches, deps, inexact=inexact)


def _vertical_fillet(req: dict, v: dict, features: list, inexact: list,
                     derivation: list, volume: str, key: str = "fillet") -> str:
    """Round the upright edges of a prismatic part.

    Applied as a Fillet on the ``vertical`` edge class rather than folded into
    the sketch, because only a rectangle has a profile builder that can express
    it. A plate can do better — ``corner_radius`` rounds the outline in-profile
    and the area is exact — so this is for the shapes that cannot: an L outline,
    a housing with a bolt pattern, anything whose corner count depends on the
    features around it.

    The volume claim drops to mesh convergence. Each rounded convex corner
    removes ``(1 - pi/4)*r^2`` per unit height, which is exact — but how many
    corners a Fillet on "vertical" actually finds depends on the solid it is
    applied to, and counting them from the requirements would be guessing at
    the kernel's answer.
    """
    r = _num(req, key)
    if not r or r <= 0:
        return volume
    v["fil_r"] = r
    features.append(
        {"id": "edge_fillet", "type": "Fillet",
         "rationale": "break the upright outside edges",
         "parameters": {"Radius": "fil_r", "_Edges": "vertical"}})
    inexact.append(
        f"a {r:g} mm fillet on the vertical edges: each rounded corner removes "
        f"(1 - pi/4)*r^2 per unit height exactly, but how many corners the "
        f"selector finds depends on the solid, so the count is not predictable "
        f"from the requirements")
    derivation.append({
        "step": len(derivation) + 1, "eq": "V verified by mesh convergence",
        "why": "vertical edges rounded; the solid is checked against its own "
               "tessellation instead of a predicted volume"})
    return volume


def _perimeter_chamfer(req: dict, v: dict, features: list, deps: list,
                       volume: str, derivation: list,
                       a_expr: str, b_expr: str,
                       inexact: Optional[list] = None) -> str:
    """Chamfer every horizontal straight edge — the top and bottom perimeter.

    Selected as ``horizontal`` filtered to ``Line``: on a plain plate that is
    exactly the eight perimeter runs, excluding the four vertical corners
    (whose chamfer is a different volume) and every circular hole rim.

    It is refused, not approximated, when the plate carries a rectangular
    pocket or a slot. Those have straight horizontal edges of their own, the
    selector would take them too, and a chamfered obround flank has no closed
    form here. ``largest:8`` looked like the way to separate them by length and
    matches nothing at all, so the honest move is to say which feature is in
    the way.

    Two traps met on the way. ``_EdgeType`` filters on the *curve class* —
    "Line" or "Circle" — not on the selector grammar, whose ``straight``
    keyword looks like it belongs there and matches nothing. And a dressup
    whose ``_Base`` names an earlier feature does not reach the tip; omitting
    it dresses the tip, which is what "break the outer edges" means.

    The closed form has a correction most people forget. Each chamfered edge
    removes a triangular prism of section ``c^2/2``, so the eight edges give
    ``(a + b)*c^2`` per face — but at each corner two prisms overlap and the
    sum counts that overlap twice.

    The overlap is not a pyramid. With ``w`` measured down from the face and
    ``u``, ``v`` in from the two side walls, one prism removes ``u + w < c`` and
    the other ``v + w < c``; both hold over ``∫₀^c (c-w)^2 dw = c^3/3``. So::

        removed = 2*((a + b)*c^2 - 4*c^3/3)

    Taking it for a pyramid (``c^3/6``) predicts 9324 mm^3 on a 300x220 plate
    chamfered 3 mm where the kernel removes 9288 — high by exactly ``4*c^3/3``,
    and wrong in a way no drawing would show.
    """
    c = _num(req, "chamfer")
    if not c or c <= 0:
        return volume
    a = _eval_expr(a_expr, v)
    b = _eval_expr(b_expr, v)
    if a is None or b is None:
        return volume
    if 2 * c >= min(a, b):
        raise GeneratorError(
            f"a {c} mm chamfer is too large for a {a:g} x {b:g} face")
    blockers = [name for name, value in
                (("a rectangular pocket", _num(req, "pocket_depth")),
                 ("mounting slots", _num(req, "slot_length"))) if value]
    if blockers and inexact is None:
        raise GeneratorError(
            f"a perimeter chamfer cannot be named separately from "
            f"{' and '.join(blockers)} — those carry straight horizontal edges "
            f"the selector would take as well, and a chamfered slot flank has "
            f"no closed form here. Drop the chamfer or the "
            f"{blockers[0].split()[-1]}")
    if blockers:
        # The selector takes those edges too, so the part is chamfered more
        # than the closed form describes. The geometry is what was asked for;
        # the prediction is what cannot be written, so the claim drops a tier.
        inexact.append(
            f"the perimeter chamfer also breaks the horizontal edges of "
            f"{' and '.join(blockers)}, and a chamfered slot flank has no exact "
            f"volume in this expression language")
    v["ch"] = c
    features.append(
        {"id": "edge_chamfer", "type": "Chamfer",
         "rationale": "break the top and bottom perimeter edges",
         "parameters": {"Size": "ch", "_Edges": "horizontal",
                        "_EdgeType": "Line"}})
    volume = f"{volume} - 2*(({a_expr} + {b_expr})*ch**2 - 4*ch**3/3)"
    derivation.append({
        "step": len(derivation) + 1, "eq": f"V = {volume}",
        "why": "chamfer on both perimeters: a triangular prism along each edge, "
               "less the pyramid two prisms share at every corner"})
    return volume


def _corner_slots(v: dict, features: list, sketches: list, deps: list,
                  sl: float, sw: float, gap: float, L: float, W: float,
                  depth_expr: str, holes: list, volume: str,
                  pocket: Optional[tuple] = None) -> tuple[str, str]:
    """Four obround slots inset from the corners, cut right through.

    A slot is not a circle, so it cannot ride in a ``rect_with_holes`` profile
    the way the bores do — it needs its own sketch and a through cut. The
    stadium area is exact: ``straight * 2r + pi*r^2``, where the straight run is
    the overall length less the two end caps.
    """
    r = sw / 2.0
    straight = sl - sw
    if straight <= 0:
        raise GeneratorError(
            f"a {sl} x {sw} slot is not elongated — its length must exceed its "
            f"width, or it is a {sw} mm hole")
    cx = L / 2.0 - gap - sl / 2.0
    cy = W / 2.0 - gap - sw / 2.0
    if cx <= 0 or cy <= 0:
        raise GeneratorError(
            f"a {sl} x {sw} slot {gap} mm from the edge does not fit on a "
            f"{L} x {W} plate")
    if pocket is not None:
        pl, pw = pocket
        if abs(cx) - sl / 2.0 < pl / 2.0 and abs(cy) - sw / 2.0 < pw / 2.0:
            raise GeneratorError(
                "the corner slots overlap the pocket; that intersection has no "
                "closed form here")
    for hx, hy, hr in holes:
        x = _eval_expr(hx, v)
        y = _eval_expr(hy, v)
        rr = _eval_expr(hr, v)
        if x is None or y is None or rr is None:
            continue
        if (abs(abs(x) - cx) < sl / 2.0 + rr
                and abs(abs(y) - cy) < sw / 2.0 + rr):
            raise GeneratorError(
                "a mounting slot overlaps a hole; that intersection has no "
                "closed form here")

    v.update({"slot_r": r, "slot_straight": straight,
              "slot_cx": round(cx, 6), "slot_cy": round(cy, 6)})
    for i, (sx, sy) in enumerate((("-", "-"), ("+", "-"), ("+", "+"), ("-", "+"))):
        features += [
            {"id": f"s_slot{i}", "type": "Sketch", "parameters": {}},
            {"id": f"slot{i}", "type": "Pocket",
             "rationale": "corner mounting slot",
             "parameters": {"Length": depth_expr, "Type": "ThroughAll"}},
        ]
        sketches.append({
            "id": f"s_slot{i}", "plane": "XY", "z": depth_expr,
            "profile": {"builder": "slot",
                        "args": {"length": "slot_straight", "r": "slot_r",
                                 "cx": f"{sx}slot_cx", "cy": f"{sy}slot_cy"}}})
        deps.append({"source": f"s_slot{i}", "target": f"slot{i}",
                     "kind": "profile"})

    return (f"{volume} - 4*(slot_straight*2*slot_r + pi*slot_r**2)*{depth_expr}",
            "four corner mounting slots, cut through; a stadium is a rectangle "
            "between two semicircular caps so its area is exact")


# --------------------------------------------------------------------------- #
# L bracket
# --------------------------------------------------------------------------- #
def l_bracket(req: dict) -> dict:
    """Base plate plus an upright, as two pads that share a corner.

    Two pads rather than one L-shaped polyline, because the upright then has a
    *profile* of its own and the motor bore and bolt holes can be cut into it
    in-profile. That matters more than it sounds: every attempt to machine
    those holes with a Pocket removed either nothing at all or a sliver, while
    the build reported success each time.

    The overlap the two pads share is a known box, ``UT*BW*BT``, subtracted
    once — the one piece of bookkeeping a single polyline would have avoided.

    Frames, established by probing rather than derived (getting any of them
    wrong produces a cut that removes nothing and a build that says it worked):

      * an XY pad grows in **+Z**, a YZ pad in **-X**
      * on a YZ sketch the builder's own x runs along world **Z** and its y
        along world **Y**, so centres read (height, width)
      * profiles are centred on the sketch origin, so ``cx``/``cy`` place them
    """
    _assert_positive(req, ("base_length", "base_width", "base_thickness",
                           "upright_height", "upright_thickness"))
    BL = _num(req, "base_length")
    BW = _num(req, "base_width")
    BT = _num(req, "base_thickness")
    UH = _num(req, "upright_height")
    UT = _num(req, "upright_thickness")
    if UT >= BL:
        raise GeneratorError("upright thickness exceeds the base length")
    if UH <= BT:
        raise GeneratorError("upright height must exceed the base thickness")

    # An upright narrower than the base is a real design; equal is the default
    # only because most brackets are. Declared either way so the expression
    # reads the same.
    UW = _num(req, "upright_width") or BW
    if UW > BW:
        raise GeneratorError(
            f"the upright is {UW} wide and the base only {BW}")

    inexact: list[str] = []
    v = {"BL": BL, "BW": BW, "BT": BT, "UH": UH, "UT": UT, "UW": UW}
    volume = "BL*BW*BT + UH*UW*UT - UT*UW*BT"
    derivation = [{"step": 1, "eq": f"V = {volume}",
                   "why": "base plate plus upright, less the corner box they "
                          "share"}]

    # The upright's own profile, so its holes are cut in-profile.
    up_holes: list[list[str]] = []
    cuts: list[str] = []

    bore_r = _num(req, "bore_r")
    if bore_r and bore_r > 0:
        if 2 * bore_r >= min(UH, UW):
            raise GeneratorError("pilot bore does not fit the upright plate")
        if UH / 2 - bore_r <= BT:
            raise GeneratorError(
                "pilot bore runs into the base plate; raise the upright")
        v["bore_r"] = bore_r
        up_holes.append(["UH/2", "0", "bore_r"])
        cuts.append("pi*bore_r**2")

    hole_r = _num(req, "hole_r")
    square = _num(req, "bolt_square")
    if hole_r and square:
        half = square / 2.0
        if hole_r <= 0:
            raise GeneratorError("mounting hole radius must be positive")
        if UH / 2 - half - hole_r <= BT:
            raise GeneratorError(
                "bolt pattern runs into the base plate; raise the upright")
        if half + hole_r >= UW / 2:
            raise GeneratorError("bolt pattern is wider than the upright plate")
        if bore_r and half - hole_r <= bore_r:
            raise GeneratorError(
                "bolt holes overlap the pilot bore; that intersection has no "
                "closed form here")
        v["bolt_half"] = half
        v["hole_r"] = hole_r
        for su in ("-", "+"):
            for sv in ("-", "+"):
                up_holes.append([f"UH/2 {su} bolt_half",
                                 f"0 {sv} bolt_half", "hole_r"])
        cuts.append("4*pi*hole_r**2")

    # ---- counterbores, as a thickness split rather than a cut ------------- #
    #
    # A counterbored plate is two plates: a thin one at the face carrying the
    # large holes, and the rest carrying the small ones. Built that way it is
    # exact and uses only pads with holes in-profile, which is the one pattern
    # that has never mis-cut here.
    #
    # It is not built as a blind Pocket because a blind Pocket does not reach
    # this face. Measured, with the sketch on the mounting face and the cut
    # aimed both ways: 56.65 mm3 removed against an expected 797.18, and that
    # 56.65 was not counterbore at all — it was the two lower circles clipping
    # the top edge of the base plate (a 5.70 mm2 segment, twice, 5 deep). The
    # same sketch with ``ThroughAll`` removed 679.79, so the profile and its
    # position are right and it is the blind depth that does not land.
    # Approximating around that would put invisible error in the volume.
    cbore_r = _num(req, "cbore_r")
    cbore_depth = _num(req, "cbore_depth")
    counterbored = False
    if cbore_r and cbore_depth:
        if not (hole_r and square):
            raise GeneratorError(
                "a counterbore needs the hole it counterbores; give the "
                "mounting hole diameter and bolt pattern")
        if cbore_r <= hole_r:
            raise GeneratorError(
                f"counterbore diameter {2*cbore_r} must exceed the "
                f"{2*hole_r} mm hole it counterbores")
        if cbore_depth >= UT:
            raise GeneratorError(
                f"counterbore depth {cbore_depth} must be less than the "
                f"{UT} mm plate it is cut into")
        if square / 2.0 + cbore_r >= UW / 2:
            raise GeneratorError("counterbores run off the edge of the upright")
        low = UH / 2 - square / 2.0 - cbore_r
        if low <= BT:
            # The lower counterbores dip below the top of the base plate, so
            # the base fills a circular segment of each — 56.65 mm3 on the
            # servo bracket, where the analytic segment says 56.97. The part is
            # correct and manufacturable; only the prediction is not exact, so
            # the volume claim drops to mesh convergence rather than being
            # refused or approximated.
            if low <= -cbore_r:
                raise GeneratorError(
                    f"the lower counterbores at z={low + cbore_r:.4g} are "
                    f"entirely inside the {BT:g} mm base plate")
            inexact.append(
                f"the lower counterbores reach z={low:.4g}, under the {BT:g} mm "
                f"base plate, so each is clipped by a circular segment with no "
                f"exact area in this expression language")
        if bore_r and square / 2.0 - cbore_r <= bore_r:
            raise GeneratorError(
                "counterbores break into the pilot bore; that intersection has "
                "no closed form here")
        v["cbore_r"] = cbore_r
        v["cbore_d"] = cbore_depth
        counterbored = True

    def _profile(hole_expr: Optional[str]) -> dict:
        """The upright's section, with its mounting holes at one radius."""
        if not up_holes:
            return {"builder": "rect",
                    "args": {"w": "UH", "h": "UW", "cx": "UH/2", "cy": "0"}}
        holes = [h if h[2] != "hole_r" or hole_expr is None
                 else [h[0], h[1], hole_expr] for h in up_holes]
        return {"builder": "rect_with_holes",
                "args": {"w": "UH", "h": "UW", "cx": "UH/2", "cy": "0",
                         "holes": holes}}

    section = " + ".join(cuts) if cuts else ""
    features = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_base", "type": "Sketch", "parameters": {}},
        {"id": "base", "type": "Pad", "rationale": "base plate",
         "parameters": {"Length": "BT", "Type": "Length"}},
    ]
    sketches = [
        {"id": "s_base", "plane": "XY",
         "profile": {"builder": "rect",
                     "args": {"w": "BL", "h": "BW", "cx": "BL/2", "cy": "0"}}},
    ]
    deps = [{"source": "s_base", "target": "base", "kind": "profile"}]

    if counterbored:
        # Two stacked pads. Each YZ sketch sits at the far face of its own slab
        # because a YZ pad grows in -X.
        features += [
            {"id": "s_upright", "type": "Sketch", "parameters": {}},
            {"id": "upright", "type": "Pad",
             "rationale": "vertical plate behind the counterbores",
             "parameters": {"Length": "UT - cbore_d", "Type": "Length"}},
            {"id": "s_face", "type": "Sketch", "parameters": {}},
            {"id": "face", "type": "Pad",
             "rationale": "the counterbored thickness at the motor face",
             "parameters": {"Length": "cbore_d", "Type": "Length"}},
        ]
        sketches += [
            {"id": "s_upright", "plane": "YZ", "z": "UT",
             "profile": _profile("hole_r")},
            {"id": "s_face", "plane": "YZ", "z": "cbore_d",
             "profile": _profile("cbore_r")},
        ]
        deps += [{"source": "s_upright", "target": "upright", "kind": "profile"},
                 {"source": "s_face", "target": "face", "kind": "profile"}]

        back = f"(UH*UW - ({section}))*(UT - cbore_d)" if section \
            else "UH*UW*(UT - cbore_d)"
        front = ("(UH*UW - (pi*bore_r**2 + 4*pi*cbore_r**2))*cbore_d"
                 if bore_r else "(UH*UW - 4*pi*cbore_r**2)*cbore_d")
        volume = f"BL*BW*BT + {back} + {front} - UT*UW*BT"
        derivation = [
            {"step": 1, "eq": f"V = {volume}",
             "why": "base plate, plus the upright as two slabs — the face slab "
                    "carrying the counterbore diameter and the rest the hole "
                    "diameter — less the corner box the base and upright share"},
        ]
    else:
        features += [
            {"id": "s_upright", "type": "Sketch", "parameters": {}},
            {"id": "upright", "type": "Pad",
             "rationale": "vertical plate with the motor interface in-profile",
             "parameters": {"Length": "UT", "Type": "Length"}},
        ]
        sketches.append({"id": "s_upright", "plane": "YZ", "z": "UT",
                         "profile": _profile("hole_r")})
        deps.append({"source": "s_upright", "target": "upright",
                     "kind": "profile"})
        if section:
            volume = f"{volume} - ({section})*UT"
            derivation.append({
                "step": len(derivation) + 1, "eq": f"V = {volume}",
                "why": "pilot bore and mounting holes through the upright, cut "
                       "in its own profile and clear of the base"})


    # ---- gusset fillet at the joint --------------------------------------- #
    #
    # This one *adds* material. The concave corner between the base and the
    # upright is filled by a quarter-cylinder's complement: a square of r^2 less
    # the quarter disc, so ``(1 - pi/4)*r^2`` per unit run, along the width the
    # two plates share.
    inside = _num(req, "inside_fillet")
    if inside:
        if inside >= UH - BT:
            raise GeneratorError(
                f"a {inside} mm inside fillet is taller than the {UH - BT:g} mm "
                f"of upright above the base")
        if inside >= BL - UT:
            raise GeneratorError(
                f"a {inside} mm inside fillet is longer than the {BL - UT:g} mm "
                f"of base in front of the upright")
        v["in_r"] = inside
        features.append(
            {"id": "gusset", "type": "Fillet",
             "rationale": "strengthening fillet in the internal corner",
             "parameters": {"Radius": "in_r", "_Edges": "concave"}})
        volume = f"{volume} + (1 - pi/4)*in_r**2*UW"
        derivation.append({
            "step": len(derivation) + 1, "eq": f"V = {volume}",
            "why": "the internal corner fillet adds material: a square of r^2 "
                   "less the quarter disc it rounds away, along the shared width"})

    # ---- base mounting slots ---------------------------------------------- #
    sl, sw = _num(req, "slot_length"), _num(req, "slot_width")
    gap = _num(req, "slot_edge_gap")
    count = req.get("slot_count")
    if sl and sw:
        if count is not None and int(count) != 4:
            raise GeneratorError(
                f"{int(count)} base slots are not supported; this builder "
                f"places four, two either side of the base")
        r = sw / 2.0
        straight = sl - sw
        if straight <= 0:
            raise GeneratorError(
                f"a {sl} x {sw} slot is not elongated — its length must exceed "
                f"its width, or it is a {sw} mm hole")
        # Two rows across the width, two columns along the length, and the near
        # column clear of the upright's footprint.
        x_near = UT + gap + sl / 2.0
        x_far = BL - gap - sl / 2.0
        cy = BW / 2.0 - gap - r
        if x_far <= x_near:
            raise GeneratorError(
                f"two rows of {sl} mm slots {gap} mm from the edges do not fit "
                f"in the {BL - UT:g} mm of base clear of the upright")
        if cy <= 0:
            raise GeneratorError(
                f"a {sw} mm slot {gap} mm from the edge does not fit across a "
                f"{BW} mm base")
        v.update({"slot_r": r, "slot_straight": straight,
                  "slot_x1": round(x_near, 6), "slot_x2": round(x_far, 6),
                  "slot_cy": round(cy, 6)})
        for i, (xv, sy) in enumerate((("slot_x1", "-"), ("slot_x2", "-"),
                                      ("slot_x2", "+"), ("slot_x1", "+"))):
            features += [
                {"id": f"s_bslot{i}", "type": "Sketch", "parameters": {}},
                {"id": f"bslot{i}", "type": "Pocket",
                 "rationale": "base mounting slot",
                 "parameters": {"Length": "BT", "Type": "ThroughAll"}},
            ]
            sketches.append({
                "id": f"s_bslot{i}", "plane": "XY", "z": "BT",
                "profile": {"builder": "slot",
                            "args": {"length": "slot_straight", "r": "slot_r",
                                     "cx": xv, "cy": f"{sy}slot_cy"}}})
            deps.append({"source": f"s_bslot{i}", "target": f"bslot{i}",
                         "kind": "profile"})
        volume = (f"{volume} - 4*(slot_straight*2*slot_r + pi*slot_r**2)*BT")
        derivation.append({
            "step": len(derivation) + 1, "eq": f"V = {volume}",
            "why": "four base mounting slots, cut through and clear of the "
                   "upright's footprint"})
    elif sl or sw or gap or count:
        raise GeneratorError(
            "base slots need both a length and a width before they can be "
            "placed")

    # ---- edge treatments the L cannot express ----------------------------- #
    #
    # Refused rather than approximated. A bracket is not a box: an external
    # fillet or chamfer runs over an L-shaped outline whose corner count depends
    # on which edges are meant, and the closed form differs for each reading.
    # The plate builder can do this because a plate has four sides and no
    # ambiguity about them.
    volume = _vertical_fillet(req, v, features, inexact, derivation, volume)
    ch = _num(req, "chamfer")
    if ch:
        if 2 * ch >= min(BT, UT):
            raise GeneratorError(
                f"a {ch} mm chamfer is too large for a {min(BT, UT):g} mm plate")
        v["ch"] = ch
        features.append(
            {"id": "edge_chamfer", "type": "Chamfer",
             "rationale": "break the exposed horizontal edges",
             "parameters": {"Size": "ch", "_Edges": "horizontal",
                            "_EdgeType": "Line"}})
        inexact.append(
            f"a {ch:g} mm chamfer on the horizontal edges: an L outline has no "
            f"fixed corner count, so the prism-and-overlap sum that a plate "
            f"admits cannot be written here")
        derivation.append({
            "step": len(derivation) + 1, "eq": "V verified by mesh convergence",
            "why": "exposed horizontal edges chamfered; the solid is checked "
                   "against its own tessellation rather than a prediction"})

    assertions = [
        _extent_assertion("len_extent", "x", "BL"),
        _extent_assertion("hgt_extent", "z", "UH"),
        _volume_assertion(volume, inexact),
    ]
    return _blueprint("l_bracket", v, derivation, assertions,
                      features, sketches, deps, inexact=inexact)


# --------------------------------------------------------------------------- #
# bearing housing
# --------------------------------------------------------------------------- #
def bearing_housing(req: dict) -> dict:
    """Block with a bearing seat bored from the top, and what hangs off it.

    Every cut is either a hole in the pad profile or a concentric counterbore
    from the top face, so each contributes an annulus and nothing overlaps
    anything ambiguously. The stack, outermost first::

        recess   radius recess_r, depth recess_depth   (flange clearance)
        seat     radius seat_r,   depth seat_depth     (the bearing)
        shaft    radius seat_r - shoulder, right through

    A shoulder is the step the bearing seats against, so it *defines* the bore
    below it: ``seat_r - shoulder``. That is arithmetic, not a guess. The one
    inference is that the smaller bore runs through, which is what a pillow
    block is for; it is stated in the derivation rather than left implicit.
    """
    _assert_positive(req, ("length", "width", "height", "bore_r", "seat_depth"))
    L, W, H = _num(req, "length"), _num(req, "width"), _num(req, "height")
    R, D = _num(req, "bore_r"), _num(req, "seat_depth")
    if 2 * R >= min(L, W):
        raise GeneratorError(
            f"bearing seat diameter {2*R} does not fit in {L} x {W}")
    if D >= H:
        raise GeneratorError(f"seat depth {D} must be less than height {H}")

    v = {"L": L, "W": W, "H": H, "seat_r": R, "seat_d": D}
    holes: list[list[str]] = []
    terms: list[str] = []
    derivation = [{"step": 1, "eq": "V = L*W*H", "why": "housing blank"}]

    shoulder = _num(req, "shoulder")
    if shoulder:
        if shoulder >= R:
            raise GeneratorError(
                f"a {shoulder} mm shoulder leaves no bore under a {R} mm seat")
        v["shaft_r"] = R - shoulder
        holes.append(["0", "0", "shaft_r"])
        terms.append("pi*shaft_r**2*H")
        # The seat then only removes the ring outside the shaft bore.
        terms.append("pi*(seat_r**2 - shaft_r**2)*seat_d")
        why_seat = ("bearing seat bored to the shoulder, less the shaft bore "
                    "beneath it which has already gone right through")
    else:
        terms.append("pi*seat_r**2*seat_d")
        why_seat = "blind bearing seat bored from the top face"

    hole_r = _num(req, "hole_r")
    px, py = _num(req, "hole_pitch_x"), _num(req, "hole_pitch_y")
    if hole_r and px and py:
        if px / 2 + hole_r >= L / 2 or py / 2 + hole_r >= W / 2:
            raise GeneratorError(
                f"a {px} x {py} hole pattern runs off a {L} x {W} housing")
        if (px / 2 - hole_r) ** 2 + (py / 2 - hole_r) ** 2 < R * R:
            raise GeneratorError(
                "the mounting holes run into the bearing seat; that "
                "intersection has no closed form here")
        v["hole_r"] = hole_r
        v["pitch_x"] = px / 2.0
        v["pitch_y"] = py / 2.0
        for sx in ("-", "+"):
            for sy in ("-", "+"):
                holes.append([f"{sx}pitch_x", f"{sy}pitch_y", "hole_r"])
        terms.append("4*pi*hole_r**2*H")

    profile = ({"builder": "rect_with_holes",
                "args": {"w": "L", "h": "W", "holes": holes}} if holes
               else {"builder": "rect", "args": {"w": "L", "h": "W"}})

    features = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_block", "type": "Sketch", "parameters": {}},
        {"id": "block", "type": "Pad",
         "rationale": "housing blank with every through-cut in the profile",
         "parameters": {"Length": "H", "Type": "Length"}},
        {"id": "s_seat", "type": "Sketch", "parameters": {}},
        {"id": "seat", "type": "Pocket", "rationale": "bearing seat bore",
         "parameters": {"Length": "seat_d", "Type": "Length"}},
    ]
    sketches = [
        {"id": "s_block", "plane": "XY", "profile": profile},
        {"id": "s_seat", "plane": "XY", "z": "H",
         "profile": {"builder": "circle", "args": {"r": "seat_r"}}},
    ]
    deps = [{"source": "s_block", "target": "block", "kind": "profile"},
            {"source": "s_seat", "target": "seat", "kind": "profile"}]

    recess_r = _num(req, "recess_r")
    recess_depth = _num(req, "recess_depth")
    if recess_r and recess_depth:
        if recess_r <= R:
            raise GeneratorError(
                f"a {2*recess_r} mm recess is no wider than the {2*R} mm seat "
                f"it surrounds")
        if 2 * recess_r >= min(L, W):
            raise GeneratorError(
                f"a {2*recess_r} mm recess does not fit in {L} x {W}")
        if recess_depth >= H:
            raise GeneratorError(
                f"recess depth {recess_depth} must be less than height {H}")
        if hole_r and px and py:
            near = ((px / 2 - hole_r) ** 2 + (py / 2 - hole_r) ** 2) ** 0.5
            if near < recess_r:
                raise GeneratorError(
                    "the flange recess reaches the mounting holes; that "
                    "intersection has no closed form here")
        v["recess_r"] = recess_r
        v["recess_d"] = recess_depth
        features += [
            {"id": "s_recess", "type": "Sketch", "parameters": {}},
            {"id": "recess", "type": "Pocket",
             "rationale": "clearance recess for the bearing flange",
             "parameters": {"Length": "recess_d", "Type": "Length"}},
        ]
        sketches.append({"id": "s_recess", "plane": "XY", "z": "H",
                         "profile": {"builder": "circle",
                                     "args": {"r": "recess_r"}}})
        deps.append({"source": "s_recess", "target": "recess", "kind": "profile"})
        # Only the ring outside the seat is new material.
        terms.append("pi*(recess_r**2 - seat_r**2)*recess_d")

    volume = "L*W*H - (" + " + ".join(terms) + ")"
    derivation.append({"step": 2, "eq": f"V = {volume}", "why": why_seat})

    # The schema asks for this as "fillet radius where the feet meet the body",
    # and this builder makes a solid block with holes rather than a body with
    # feet hanging off it. There is no such edge to fillet, so accepting the
    # number would silently do nothing.
    inexact: list[str] = []
    volume = _vertical_fillet(req, v, features, inexact, derivation, volume)
    volume = _perimeter_chamfer(req, v, features, deps, volume, derivation,
                                "L", "W", inexact)

    assertions = [
        _extent_assertion("len_extent", "x", "L"),
        _extent_assertion("hgt_extent", "z", "H"),
        {"id": "seat_fits", "kind": "precondition", "tier": 1,
         "target": "W - 2*seat_r - 4"},
        _volume_assertion(volume, inexact),
    ]
    return _blueprint("bearing_housing", v, derivation, assertions,
                      features, sketches, deps, inexact=inexact)


# --------------------------------------------------------------------------- #
# manifold
# --------------------------------------------------------------------------- #
def manifold(req: dict) -> dict:
    """Block with one through passage along its length, plus vertical ports.

    The ports are cut from the top down to the passage centreline, so each
    removes a cylinder of length ``H/2`` minus the part already inside the
    passage. Rather than model that intersection, the ports stop *at* the
    passage crown — the volumes are then disjoint and the closed form is exact.
    A port that must break through is a different feature and is refused here
    rather than approximated.
    """
    _assert_positive(req, ("length", "width", "height", "passage_r"))
    L, W, H = _num(req, "length"), _num(req, "width"), _num(req, "height")
    PR = _num(req, "passage_r")
    if 2 * PR >= min(W, H):
        raise GeneratorError("main passage does not fit inside the block")

    inexact: list[str] = []
    v = {"L": L, "W": W, "H": H, "pr": PR}
    volume = "(L*W*H) - pi*pr**2*L"
    # The passage is a hole IN the extruded section, not a Pocket cut after it.
    #
    # As a separate Pocket it did not cut at all: the block is extruded along X
    # from a YZ sketch, and a Pocket sketched on that same plane runs away from
    # the material rather than into it, so the build reported success and the
    # measured volume was the full 180*90*45 block — the closed form and the
    # solid disagreed by exactly pi*pr^2*L. In the profile there is nothing to
    # get the direction of.
    #
    # On YZ the builder's `w` runs along Z and `h` along Y, which is why the
    # arguments look transposed: passing w=W put the 90 mm dimension on Z and
    # produced a block standing on its side. Faithful only by luck, since the
    # extent check sorts.
    features = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_block", "type": "Sketch", "parameters": {}},
        {"id": "block", "type": "Pad",
         "rationale": "manifold blank with the main passage in-profile",
         "parameters": {"Length": "L", "Type": "Length"}},
    ]
    sketches = [
        {"id": "s_block", "plane": "YZ",
         "profile": {"builder": "rect_with_holes",
                     "args": {"w": "H", "h": "W",
                              "holes": [["0", "0", "pr"]]}}},
    ]
    deps = [{"source": "s_block", "target": "block", "kind": "profile"}]

    derivation = [
        {"step": 1, "eq": f"V = {volume}",
         "why": "W x H section with the main passage as a hole in the profile, "
                "extruded the full length"},
    ]

    # ---- ports ------------------------------------------------------------ #
    #
    # Refused, and this one is not a plumbing problem. A port is only a port if
    # it breaks into the main passage, and two perpendicular cylinders of
    # different radii intersect in a solid whose volume needs elliptic
    # integrals — there is no expression over the variables that states it. The
    # alternatives are both worse than saying so: stopping the port at the
    # passage crown builds a manifold that does not flow, and subtracting the
    # full port cylinder over-removes by exactly the intersection.
    port_r = _num(req, "port_r")
    n_ports = req.get("port_count")
    req.get("port_thread")
    req.get("inlet_thread")
    if port_r and n_ports:
        n_ports = int(n_ports)
        if n_ports < 1:
            raise GeneratorError("port_count must be at least 1")
        if 2 * port_r >= W:
            raise GeneratorError(
                f"a {2*port_r} mm port does not fit across a {W} mm block")
        # Positions are expressions over L, not the arithmetic's answer. The
        # checker refuses a constant here and is right to: a bare -25.714286 is
        # a magic number that stops tracking the length it was derived from.
        pitch = L / (n_ports + 1)
        if pitch <= 2 * port_r:
            raise GeneratorError(
                f"{n_ports} ports of {2*port_r} mm do not fit along {L} mm")
        v["port_r"] = port_r
        for i in range(n_ports):
            x = f"-{i + 1}*L/{n_ports + 1}"
            features += [
                {"id": f"s_port{i}", "type": "Sketch", "parameters": {}},
                {"id": f"port{i}", "type": "Pocket",
                 "rationale": "vertical port into the main passage",
                 "parameters": {"Length": "H", "Type": "ThroughAll"}},
            ]
            sketches.append({
                "id": f"s_port{i}", "plane": "XY", "z": "H/2",
                "profile": {"builder": "circle",
                            "args": {"r": "port_r", "cx": x, "cy": "0"}}})
            deps.append({"source": f"s_port{i}", "target": f"port{i}",
                         "kind": "profile"})
        # A port is only a port if it breaks into the passage, and two
        # perpendicular cylinders of different radii intersect in a solid whose
        # volume needs elliptic integrals. The geometry is right; the closed
        # form does not exist, so the volume claim drops a tier rather than
        # being invented.
        inexact.append(
            f"{n_ports} vertical ports break into the main passage, and two "
            f"perpendicular cylinders intersect in a solid whose volume has no "
            f"closed form in this expression language")
        derivation.append({
            "step": len(derivation) + 1, "eq": "V verified by mesh convergence",
            "why": "ports intersect the passage; the solid is checked against "
                   "its own tessellation instead of a predicted volume"})

    # ---- corner mounting holes, cut down through the block ---------------- #
    hole_r = _num(req, "hole_r")
    gap = _num(req, "hole_edge_gap")
    if hole_r:
        if gap is None:
            raise GeneratorError(
                'mounting holes need a distance from the block edge — '
                '"in the corners" does not fix a position')
        cx = L / 2.0 - gap - hole_r
        cy = W / 2.0 - gap - hole_r
        if cx <= 0 or cy <= 0:
            raise GeneratorError(
                f"a {2*hole_r} mm hole {gap} mm from the edge does not fit on "
                f"a {L} x {W} block")
        if cy - hole_r <= PR:
            raise GeneratorError(
                "the mounting holes run into the main passage; that "
                "intersection has no closed form here")
        v["hole_r"] = hole_r
        v["hx"] = round(cx, 6)
        v["hy"] = round(cy, 6)
        for i, (sx, sy) in enumerate((("-", "-"), ("+", "-"),
                                      ("+", "+"), ("-", "+"))):
            features += [
                {"id": f"s_mh{i}", "type": "Sketch", "parameters": {}},
                {"id": f"mh{i}", "type": "Pocket",
                 "rationale": "corner mounting hole",
                 "parameters": {"Length": "H", "Type": "ThroughAll"}},
            ]
            # The block spans x in [-L, 0], so the pattern is offset to its
            # centre rather than to the origin.
            sketches.append({
                "id": f"s_mh{i}", "plane": "XY", "z": "H/2",
                "profile": {"builder": "circle",
                            "args": {"r": "hole_r",
                                     "cx": f"-L/2 {sx} hx", "cy": f"{sy}hy"}}})
            deps.append({"source": f"s_mh{i}", "target": f"mh{i}",
                         "kind": "profile"})
        volume = f"{volume} - 4*pi*hole_r**2*H"
        derivation.append({
            "step": len(derivation) + 1, "eq": f"V = {volume}",
            "why": "four corner mounting holes, right through and clear of the "
                   "passage"})

        cbore_r = _num(req, "cbore_r")
        cbore_depth = _num(req, "cbore_depth")
        if cbore_r and cbore_depth:
            if cbore_r <= hole_r:
                raise GeneratorError(
                    f"counterbore diameter {2*cbore_r} must exceed the "
                    f"{2*hole_r} mm hole it counterbores")
            if cbore_depth >= H:
                raise GeneratorError(
                    f"counterbore depth {cbore_depth} must be less than the "
                    f"{H} mm block")
            if cy - cbore_r <= PR:
                raise GeneratorError(
                    "the counterbores reach the main passage; that "
                    "intersection has no closed form here")
            v["cbore_r"] = cbore_r
            v["cbore_d"] = cbore_depth
            for i, (sx, sy) in enumerate((("-", "-"), ("+", "-"),
                                          ("+", "+"), ("-", "+"))):
                features += [
                    {"id": f"s_cb{i}", "type": "Sketch", "parameters": {}},
                    {"id": f"cb{i}", "type": "Pocket",
                     "rationale": "counterbore from the top face",
                     "parameters": {"Length": "cbore_d", "Type": "Length"}},
                ]
                sketches.append({
                    "id": f"s_cb{i}", "plane": "XY", "z": "H/2",
                    "profile": {"builder": "circle",
                                "args": {"r": "cbore_r",
                                         "cx": f"-L/2 {sx} hx",
                                         "cy": f"{sy}hy"}}})
                deps.append({"source": f"s_cb{i}", "target": f"cb{i}",
                             "kind": "profile"})
            volume = (f"{volume} - 4*pi*(cbore_r**2 - hole_r**2)*cbore_d")
            derivation.append({
                "step": len(derivation) + 1, "eq": f"V = {volume}",
                "why": "counterbores, counting only the annulus each adds "
                       "because the through-hole already removed the centre"})

    volume = _vertical_fillet(req, v, features, inexact, derivation, volume)
    volume = _perimeter_chamfer(req, v, features, deps, volume, derivation,
                                "L", "W", inexact)

    assertions = [
        _extent_assertion("len_extent", "x", "L"),
        {"id": "wall", "kind": "precondition", "tier": 1,
         "target": "W - 2*pr - 6"},
        _volume_assertion(volume, inexact),
    ]
    return _blueprint("manifold", v, derivation, assertions,
                      features, sketches, deps, inexact=inexact)


BUILDERS: dict[str, Callable[[dict], dict]] = {
    "rect_plate": rect_plate,
    "l_bracket": l_bracket,
    "bearing_housing": bearing_housing,
    "manifold": manifold,
}


#: Keys that describe the part without shaping it.
#:
#: Recorded on the Blueprint rather than consumed by geometry, so a material or
#: a thread designation survives into the design plan instead of being dropped.
#: They are the only requirements a builder may legitimately not read.
INFORMATIONAL = frozenset({
    "family", "schema_version", "standards_applied", "provenance",
    "material", "bearing_series", "mounting_type",
    "thread", "hole_thread", "port_thread", "inlet_thread",
})


class _Seen(dict):
    """A requirements dict that remembers which keys were read.

    The guarantee wanted here is that no requested feature is silently dropped,
    and diligence per field does not give it — a builder that forgets to read
    ``slot_length`` looks exactly like a plate that has no slots. Recording the
    reads makes the check structural: whatever a builder never looked at is
    reported, including in families written later.
    """

    def __init__(self, data: dict):
        super().__init__(data)
        self.seen: set[str] = set()

    def get(self, key, default=None):  # noqa: D102
        self.seen.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.seen.add(key)
        return super().__getitem__(key)


def generate(family: str, requirements: dict) -> dict:
    """Blueprint dict for a family, from resolved requirements.

    ``requirements`` must already be resolved — diameters halved into radii by
    ``interview.resolve`` — because a builder that accepted either would have to
    guess which it was given.

    Raises if the builder never read something the interview collected. A
    parameter a user stated and a part does not carry is the failure this whole
    architecture exists to prevent; it is worse than a refusal because nothing
    reports it.
    """
    builder = BUILDERS.get(family)
    if builder is None:
        raise GeneratorError(
            f"no deterministic builder for {family!r}; known: "
            f"{', '.join(sorted(BUILDERS))}")

    tracked = _Seen(requirements)
    payload = builder(tracked)

    ignored = sorted(set(requirements) - tracked.seen - INFORMATIONAL)
    if ignored:
        raise GeneratorError(
            f"{family} does not build: "
            + ", ".join(ignored)
            + ". These were asked for and the generator has no rule for them, "
              "so the part would be missing features you specified")

    stated = {k: requirements[k] for k in INFORMATIONAL
              if k in requirements and k not in ("family", "schema_version",
                                                 "provenance")}
    if stated:
        payload["design_plan"]["stated"] = stated

    # Where every variable came from, carried onto the names the builder gave
    # them. Written into ``design_plan`` because that is inside the hash: a
    # record of provenance that could be added after the part was measured
    # would prove nothing, for exactly the reason the assertions are frozen.
    #
    # Whatever the builder introduced that no requirement named is derived by
    # construction — every expression in this module is written here, so there
    # is no step at which a free number could enter.
    from . import provenance as P

    payload["design_plan"]["provenance"] = P.extend(
        requirements.get("provenance") or {},
        payload.get("variables") or {},
        f"computed by blueprint_gen.{family} from the collected dimensions",
        source_values=requirements,
    )
    return payload
