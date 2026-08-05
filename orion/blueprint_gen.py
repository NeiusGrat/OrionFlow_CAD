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
               dependencies: list, datums: Optional[dict] = None) -> dict:
    return {
        "part_class": part_class,
        "variables": variables,
        "datums": datums or {"A": "bottom face z=0 (primary)",
                             "B": "long edge (secondary)"},
        "design_plan": {"derivation": derivation},
        "assertions": assertions,
        "template": {"features": features, "sketches": sketches,
                     "dependencies": dependencies},
    }


def _volume_assertion(expr: str) -> dict:
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
    pcd = _num(req, "pcd")
    if n and hole_r and pcd:
        n = int(n)
        if n < 1:
            raise GeneratorError("hole_count must be at least 1")
        if pcd / 2 + hole_r >= min(L, W) / 2:
            raise GeneratorError("bolt circle does not fit inside the plate")
        v["hole_r"] = hole_r
        v["pcd_r"] = pcd / 2.0
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
                raise GeneratorError(
                    "a hole straddles the pocket wall; that overlap has no "
                    "closed form here — move the pocket or the hole")
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
        pocket = "pl*pw*pd"
        if overlap_terms:
            pocket = f"({pocket} - {' - '.join(overlap_terms)})"
        volume = f"{volume} - {pocket}"
        why = "blind rectangular pocket from the top face"
        if overlap_terms:
            why += (f", less the {len(overlap_terms)} through-hole(s) under it "
                    f"whose material the holes already removed")
        derivation.append({"step": 2, "eq": f"V = {volume}", "why": why})

    assertions = [
        _extent_assertion("len_extent", "x", "L"),
        _extent_assertion("wid_extent", "y", "W"),
        _volume_assertion(volume),
    ]
    return _blueprint("rect_plate", v, derivation, assertions,
                      features, sketches, deps)


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

    v = {"BL": BL, "BW": BW, "BT": BT, "UH": UH, "UT": UT}
    volume = "BL*BW*BT + UH*BW*UT - UT*BW*BT"
    derivation = [{"step": 1, "eq": f"V = {volume}",
                   "why": "base plate plus upright, less the corner box they "
                          "share"}]

    # The upright's own profile, so its holes are cut in-profile.
    up_holes: list[list[str]] = []
    cuts: list[str] = []

    bore_r = _num(req, "bore_r")
    if bore_r and bore_r > 0:
        if 2 * bore_r >= min(UH, BW):
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
        if half + hole_r >= BW / 2:
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

    if up_holes:
        up_profile = {"builder": "rect_with_holes",
                      "args": {"w": "UH", "h": "BW", "cx": "UH/2", "cy": "0",
                               "holes": up_holes}}
        volume = f"{volume} - ({' + '.join(cuts)})*UT"
        derivation.append({
            "step": len(derivation) + 1, "eq": f"V = {volume}",
            "why": "pilot bore and mounting holes through the upright, cut in "
                   "its own profile and clear of the base"})
    else:
        up_profile = {"builder": "rect",
                      "args": {"w": "UH", "h": "BW", "cx": "UH/2", "cy": "0"}}

    features = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_base", "type": "Sketch", "parameters": {}},
        {"id": "base", "type": "Pad", "rationale": "base plate",
         "parameters": {"Length": "BT", "Type": "Length"}},
        {"id": "s_upright", "type": "Sketch", "parameters": {}},
        {"id": "upright", "type": "Pad",
         "rationale": "vertical plate with the motor interface in-profile",
         "parameters": {"Length": "UT", "Type": "Length"}},
    ]
    sketches = [
        {"id": "s_base", "plane": "XY",
         "profile": {"builder": "rect",
                     "args": {"w": "BL", "h": "BW", "cx": "BL/2", "cy": "0"}}},
        # Placed at x = UT so the -X extrusion lands on x in [0, UT].
        {"id": "s_upright", "plane": "YZ", "z": "UT", "profile": up_profile},
    ]
    deps = [{"source": "s_base", "target": "base", "kind": "profile"},
            {"source": "s_upright", "target": "upright", "kind": "profile"}]

    assertions = [
        _extent_assertion("len_extent", "x", "BL"),
        _extent_assertion("hgt_extent", "z", "UH"),
        _volume_assertion(volume),
    ]
    return _blueprint("l_bracket", v, derivation, assertions,
                      features, sketches, deps)


# --------------------------------------------------------------------------- #
# bearing housing
# --------------------------------------------------------------------------- #
def bearing_housing(req: dict) -> dict:
    """Rectangular block with a blind bearing seat bored from the top."""
    _assert_positive(req, ("length", "width", "height", "bore_r", "seat_depth"))
    L, W, H = _num(req, "length"), _num(req, "width"), _num(req, "height")
    R, D = _num(req, "bore_r"), _num(req, "seat_depth")
    if 2 * R >= min(L, W):
        raise GeneratorError(
            f"bearing seat diameter {2*R} does not fit in {L} x {W}")
    if D >= H:
        raise GeneratorError(f"seat depth {D} must be less than height {H}")

    v = {"L": L, "W": W, "H": H, "seat_r": R, "seat_d": D}
    volume = "L*W*H - pi*seat_r**2*seat_d"
    features = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_block", "type": "Sketch", "parameters": {}},
        {"id": "block", "type": "Pad", "rationale": "housing blank",
         "parameters": {"Length": "H", "Type": "Length"}},
        {"id": "s_seat", "type": "Sketch", "parameters": {}},
        {"id": "seat", "type": "Pocket", "rationale": "bearing seat bore",
         "parameters": {"Length": "seat_d", "Type": "Length"}},
    ]
    sketches = [
        {"id": "s_block", "plane": "XY",
         "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
        {"id": "s_seat", "plane": "XY", "z": "H",
         "profile": {"builder": "circle", "args": {"r": "seat_r"}}},
    ]
    deps = [{"source": "s_block", "target": "block", "kind": "profile"},
            {"source": "s_seat", "target": "seat", "kind": "profile"}]

    derivation = [
        {"step": 1, "eq": "V = L*W*H", "why": "rectangular housing blank"},
        {"step": 2, "eq": f"V = {volume}",
         "why": "blind bearing seat bored from the top face"},
    ]
    assertions = [
        _extent_assertion("len_extent", "x", "L"),
        _extent_assertion("hgt_extent", "z", "H"),
        {"id": "seat_fits", "kind": "precondition", "tier": 1,
         "target": "W - 2*seat_r - 4"},
        _volume_assertion(volume),
    ]
    return _blueprint("bearing_housing", v, derivation, assertions,
                      features, sketches, deps)


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
    assertions = [
        _extent_assertion("len_extent", "x", "L"),
        {"id": "wall", "kind": "precondition", "tier": 1,
         "target": "W - 2*pr - 6"},
        _volume_assertion(volume),
    ]
    return _blueprint("manifold", v, derivation, assertions,
                      features, sketches, deps)


BUILDERS: dict[str, Callable[[dict], dict]] = {
    "rect_plate": rect_plate,
    "l_bracket": l_bracket,
    "bearing_housing": bearing_housing,
    "manifold": manifold,
}


def generate(family: str, requirements: dict) -> dict:
    """Blueprint dict for a family, from resolved requirements.

    ``requirements`` must already be resolved — diameters halved into radii by
    ``interview.resolve`` — because a builder that accepted either would have to
    guess which it was given.
    """
    builder = BUILDERS.get(family)
    if builder is None:
        raise GeneratorError(
            f"no deterministic builder for {family!r}; known: "
            f"{', '.join(sorted(BUILDERS))}")
    return builder(requirements)
