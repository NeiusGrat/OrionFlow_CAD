"""Static blueprint checker — the machine enforcement of "no magic numbers".

Every dimensional parameter and every profile argument must be an expression
string over the blueprint's named variables. A bare ``66.0`` in a feature is
rejected; ``"size + 26"`` passes only if ``size`` is a declared variable.

Structural constants are the one deliberate exemption: 0, ±1, and the right
angles (90/180/270/360) carry topology, not design intent, and forcing
``full_circle = 360`` into every variables block would be noise, not rigor.
"""

from __future__ import annotations

import math
import re
from typing import Any

from . import expr as E

STRUCTURAL_CONSTANTS = {0.0, 1.0, -1.0, 2.0, 90.0, 180.0, 270.0, 360.0}

#: Assertion kinds whose verdict compares a measurement against an authored
#: ``target``. ``watertight`` and ``body_mesh_converged`` derive their own
#: pass condition, and ``body_volume_profile`` reads the builder's exact area,
#: so none of them authors a target.
_TARGETED_KINDS = {"body_volume", "feature_volume", "bbox_extent", "solids",
                   "precondition"}

#: Parameters that are enums/strings/bools/links — not dimensional.
NON_DIMENSIONAL = {
    "Type", "Type2", "SideType", "Mode", "Transition", "Transformation",
    "DepthType", "DrillPoint", "ThreadType", "HoleCutType", "ThreadSize",
    "ThreadClass", "ThreadFit", "Threaded", "ModelThread", "Tapered",
    "Reversed", "Midplane", "Refine", "Ruled", "Closed", "Subtractive",
    "Join", "Occurrences",
}


def _is_structural(value: float) -> bool:
    return float(value) in STRUCTURAL_CONSTANTS


def _engineering_checks(bp: Any) -> list[dict]:
    """Declared engineering checks, defensively. Never raises on a malformed
    block — the shape is validated where it is run, not here."""
    plan = getattr(bp, "design_plan", None) or {}
    block = plan.get("engineering") if isinstance(plan, dict) else None
    checks = block.get("checks") if isinstance(block, dict) else None
    return [c for c in checks if isinstance(c, dict)] if isinstance(checks, list) else []


def _check_expr(where: str, value: Any, variables: dict,
                problems: list[str]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not _is_structural(value):
            problems.append(f"{where}: bare numeric literal {value!r} — "
                            f"express it over the variables block")
        return
    if not isinstance(value, str):
        return
    try:
        refs = E.names(value)
    except E.ExprError as e:
        problems.append(f"{where}: {e}")
        return
    unknown = refs - set(variables)
    if unknown:
        problems.append(f"{where}: unknown variable(s) {sorted(unknown)}")
        return
    if not refs:
        # A pure-constant expression is only fine if it is structural.
        try:
            v = E.evaluate(value, {})
        except E.ExprError as e:
            problems.append(f"{where}: {e}")
            return
        if not _is_structural(v):
            problems.append(f"{where}: constant expression {value!r} = {v} "
                            f"references no variable")


def check_blueprint(bp) -> list[str]:
    """All violations, empty list == clean. Pure static analysis."""
    problems: list[str] = []
    variables = bp.variables or {}

    for name, v in variables.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            problems.append(f"variables.{name}: must be a number, got {v!r}")
        # A variable named after a whitelisted function or constant is
        # INVISIBLE to the expression layer (name resolution prefers the
        # function), so every reference to it reads as an unknown name and
        # the variable itself looks unused. Refuse it outright.
        if name in E.FUNCTIONS or name in E.CONSTANTS:
            problems.append(
                f"variables.{name}: shadows the built-in "
                f"{'function' if name in E.FUNCTIONS else 'constant'} "
                f"{name!r} — rename it")

    used: set[str] = set()
    feature_ids: set[str] = set()

    for f in bp.template.get("features", []):
        fid = f.get("id", "?")
        if fid in feature_ids:
            problems.append(f"features.{fid}: duplicate id")
        feature_ids.add(fid)
        for k, v in (f.get("parameters") or {}).items():
            if k in NON_DIMENSIONAL or k.startswith("_"):
                continue
            _check_expr(f"features.{fid}.{k}", v, variables, problems)
            if isinstance(v, str):
                try:
                    used |= E.names(v)
                except E.ExprError:
                    pass

    for sk in bp.template.get("sketches", []):
        sid = sk.get("id", "?")
        if sid in feature_ids:
            pass  # sketches share the feature id namespace; fine
        spec = sk.get("profile")
        if not spec:
            problems.append(f"sketches.{sid}: raw geometry is forbidden — "
                            f"use a registered profile builder")
            continue
        if "geometry" in sk:
            problems.append(f"sketches.{sid}: has BOTH profile spec and raw "
                            f"geometry; raw geometry is forbidden")
        for k, v in (spec.get("args") or {}).items():
            if k in ("n", "nx", "ny", "start_deg"):
                # Instance counts, grid dimensions and clocking angles are
                # topology, not dimensions — a constant is legitimate intent.
                continue
            if k in ("holes", "points"):
                for i, item in enumerate(v):
                    for j, coord in enumerate(item):
                        _check_expr(f"sketches.{sid}.{k}[{i}][{j}]",
                                    coord, variables, problems)
                        if isinstance(coord, str):
                            try:
                                used |= E.names(coord)
                            except E.ExprError:
                                pass
                continue
            _check_expr(f"sketches.{sid}.{k}", v, variables, problems)
            if isinstance(v, str):
                try:
                    used |= E.names(v)
                except E.ExprError:
                    pass
        if "z" in sk:
            _check_expr(f"sketches.{sid}.z", sk["z"], variables, problems)
            if isinstance(sk["z"], str):
                try:
                    used |= E.names(sk["z"])
                except E.ExprError:
                    pass

    for a in bp.assertions:
        aid = a.get("id", "?")
        kind = a.get("kind")
        if "tier" not in a or a["tier"] not in (1, 2, 3):
            problems.append(f"assertions.{aid}: tier must be 1, 2 or 3")
        if "tol_rel" not in a and kind not in (
                "precondition", "watertight", "volume_between"):
            problems.append(f"assertions.{aid}: missing tol_rel")
        # The prediction side of the contract is held to the same no-magic-number
        # rule as the geometry side. A target is what the author CLAIMS the
        # kernel will measure; if it arrives as a bare number, the author did the
        # arithmetic instead of deriving it, and the one thing the verification
        # proves — that a closed form over the named variables predicts the
        # solid — is no longer being tested. Checking these only `if isinstance
        # str` (as this did) let a computed literal through the gate silently,
        # and it failed later wearing the wrong costume: resolve_assertions()
        # emits no target_value for a non-string, so forge.check_assertions saw
        # target=None and reported "no measurement" — blaming the kernel for a
        # bad authored target.
        for key in ("target", "lo", "hi"):
            if key not in a or a[key] is None:
                continue
            _check_expr(f"assertions.{aid}.{key}", a[key], variables, problems)
            if isinstance(a[key], str):
                try:
                    used |= E.names(a[key])
                except E.ExprError:
                    pass
        if kind in _TARGETED_KINDS and a.get("target") is None:
            problems.append(f"assertions.{aid}: kind {kind!r} is checked "
                            f"against a target, but none was authored")
        if kind == "volume_between" and (a.get("lo") is None
                                         or a.get("hi") is None):
            problems.append(f"assertions.{aid}: volume_between needs lo and hi")

    # Engineering checks reference the same frozen variables the geometry is
    # built from — that is the point of them, and it means a variable used only
    # by a calculator is genuinely used. Omitting this scope would report it as
    # a magic number in disguise and refuse a correct design, which is the same
    # bug the pattern-count arguments once had.
    for i, spec in enumerate(_engineering_checks(bp)):
        cid = spec.get("id") or i
        for arg, value in (spec.get("args") or {}).items():
            if not (isinstance(value, str) and value.startswith("=")):
                continue
            where = f"design_plan.engineering.{cid}.{arg}"
            _check_expr(where, value[1:], variables, problems)
            try:
                used |= E.names(value[1:])
            except E.ExprError:
                pass

    dead = set(variables) - used
    if dead:
        problems.append(f"unused variable(s): {sorted(dead)} — a variable "
                        f"nothing references is a magic number in disguise")

    for d in bp.template.get("dependencies", []):
        for end in ("source", "target"):
            ref = d.get(end)
            sketch_ids = {s.get("id") for s in bp.template.get("sketches", [])}
            if ref not in feature_ids and ref not in sketch_ids:
                problems.append(f"dependencies: {end} {ref!r} does not exist")

    return problems


# --------------------------------------------------------------------------- #
# advisories — suspicions, never rejections
# --------------------------------------------------------------------------- #
#: ``att<N>_`` variable prefix, as emitted by :func:`orion.compose.compose`.
_ATT_PREFIX = re.compile(r"^(att\d+)_c[xy]$")


def _attachment_footprint(p: str, variables: dict) -> tuple[str, float] | None:
    """``(kind, footprint_radius)`` for attachment ``p``, or None if unknown.

    Mirrors the ``footprint_expr`` each fragment in :mod:`orion.compose`
    declares. The generator uses that radius to keep siblings apart while
    sampling; recomputing it here is how a *model-authored* placement gets held
    to the same rule. Each kind is identified by the size variables it emits —
    ``br`` only exists on a bolt boss, ``cr`` only on a counterbore, and so on.
    """
    def g(suffix: str) -> float | None:
        v = variables.get(f"{p}_{suffix}")
        return float(v) if isinstance(v, (int, float)) \
            and not isinstance(v, bool) else None

    br, pr, cr, lr = g("br"), g("pr"), g("cr"), g("lr")
    if br is not None:
        return "bolt_boss", br
    if pr is not None:
        return "locating_pin", pr
    if cr is not None:
        return "counterbore_set", cr
    if lr is not None:
        return "lightening_pocket", lr
    sl, sr = g("sl"), g("sr")
    if sl is not None and sr is not None:
        return "vent_slot", sl / 2.0 + sr
    rl, rw, rt = g("rl"), g("rw"), g("rt")
    if rl is not None and rw is not None:
        return "thermal_relief", math.hypot(rl / 2.0, rw / 2.0)
    if rl is not None and rt is not None:
        return "alignment_rib", math.hypot(rl / 2.0, rt / 2.0)
    return None


def advisories(variables: dict, template: dict) -> list[str]:
    """Things that are probably wrong but are not contract violations.

    Deliberately **not** called by :func:`check_blueprint`: every string here is
    a heuristic, and a heuristic that rejects a Blueprint can only lose ground
    that the closed form would otherwise have won. These feed the repair
    diagnosis instead, where a false positive costs nothing — the model also has
    the real measurements in front of it.

    The one advisory so far is the sibling-overlap case, and it exists because
    of a specific gap. ``compose.compose`` keeps sampled attachments apart
    (``hypot(dx, dy) > r_i + r_j + 2``) but emits **no assertion** saying so —
    the same "invisible constraint" mistake it already fixed for land
    containment, left unfixed for the pairwise case. So the composed body
    expression is a plain sum of per-attachment deltas with no intersection
    term, and every part in the corpus honours that by construction. A model
    trained on it never sees the constraint, and when it later chooses centres
    of its own two attachments can overlap — at which point the sum
    double-counts the shared volume and ``body_volume`` misses by a hair. That
    is exactly the signature of the composed-part failures: a correct build with
    a sub-percent volume error.
    """
    notes: list[str] = []

    atts: dict[str, dict] = {}
    for name in variables:
        m = _ATT_PREFIX.match(name)
        if not m:
            continue
        p = m.group(1)
        if p in atts:
            continue
        cx, cy = variables.get(f"{p}_cx"), variables.get(f"{p}_cy")
        fp = _attachment_footprint(p, variables)
        if fp is None or not isinstance(cx, (int, float)) \
                or not isinstance(cy, (int, float)):
            continue
        atts[p] = {"kind": fp[0], "r": fp[1], "cx": float(cx),
                   "cy": float(cy), "z": None, "dirs": set()}

    if len(atts) < 2:
        return notes

    # Mount plane and direction, both read off the frozen template. Two
    # attachments on different planes cannot share volume however close their
    # centres are, so the plane is what makes the comparison meaningful.
    for sk in template.get("sketches", []):
        sid = str(sk.get("id", ""))
        for p in atts:
            # FIRST sketch only. A bolt boss emits two — the boss outline on the
            # mount plane and its through-hole on top of the finished boss — and
            # taking the last would record the attachment as living one boss
            # height above where it actually sits, so a real overlap with a
            # neighbour on the mount plane would look like two different planes
            # and go unreported.
            if sid.startswith(f"s_{p}_") and atts[p]["z"] is None:
                try:
                    atts[p]["z"] = round(E.evaluate(sk.get("z", 0), variables), 6)
                except (E.ExprError, TypeError, ValueError):
                    pass
                break
    from .compose import _ADDITIVE, _SUBTRACTIVE

    for f in template.get("features", []):
        fid = str(f.get("id", ""))
        for p in atts:
            if fid.startswith(f"{p}_"):
                t = f.get("type", "")
                if t in _ADDITIVE:
                    atts[p]["dirs"].add("add")
                elif t in _SUBTRACTIVE:
                    atts[p]["dirs"].add("sub")
                break

    order = sorted(atts)
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            u, v = atts[a], atts[b]
            if u["z"] is None or v["z"] is None or u["z"] != v["z"]:
                continue
            # Same reasoning as the guard in ``compose``: a Pad grows away from
            # the mount plane and a Pocket cuts into it, so an additive and a
            # subtractive attachment never share volume however close they sit.
            if not (u["dirs"] & v["dirs"]):
                continue
            gap = math.hypot(u["cx"] - v["cx"], u["cy"] - v["cy"])
            reach = u["r"] + v["r"]
            if gap >= reach:
                continue
            notes.append(
                f"{a} ({u['kind']}, r={u['r']:.3g} at "
                f"{u['cx']:.3g},{u['cy']:.3g}) and {b} ({v['kind']}, "
                f"r={v['r']:.3g} at {v['cx']:.3g},{v['cy']:.3g}) sit on the "
                f"same plane z={u['z']:.4g} and their footprints overlap "
                f"(centres {gap:.3g} apart, radii sum to {reach:.3g}). The "
                f"body volume adds each attachment's delta independently, so "
                f"the shared volume is counted twice — move one centre until "
                f"the centres are at least {reach:.3g} apart, or subtract the "
                f"intersection explicitly.")
    return notes
