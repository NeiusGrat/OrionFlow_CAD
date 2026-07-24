"""Static blueprint checker — the machine enforcement of "no magic numbers".

Every dimensional parameter and every profile argument must be an expression
string over the blueprint's named variables. A bare ``66.0`` in a feature is
rejected; ``"size + 26"`` passes only if ``size`` is a declared variable.

Structural constants are the one deliberate exemption: 0, ±1, and the right
angles (90/180/270/360) carry topology, not design intent, and forcing
``full_circle = 360`` into every variables block would be noise, not rigor.
"""

from __future__ import annotations

from typing import Any

from . import expr as E

STRUCTURAL_CONSTANTS = {0.0, 1.0, -1.0, 2.0, 90.0, 180.0, 270.0, 360.0}

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
        if "tier" not in a or a["tier"] not in (1, 2, 3):
            problems.append(f"assertions.{aid}: tier must be 1, 2 or 3")
        if "tol_rel" not in a and a.get("kind") not in (
                "precondition", "watertight", "volume_between"):
            problems.append(f"assertions.{aid}: missing tol_rel")
        for key in ("lo", "hi"):
            if isinstance(a.get(key), str):
                _check_expr(f"assertions.{aid}.{key}", a[key],
                            variables, problems)
                try:
                    used |= E.names(a[key])
                except E.ExprError:
                    pass
        if isinstance(a.get("target"), str):
            _check_expr(f"assertions.{aid}.target", a["target"],
                        variables, problems)
            try:
                used |= E.names(a["target"])
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
