"""Hand edits to a frozen Blueprint.

Two kinds of edit, and the difference between them is the whole point.

**Retuning** changes the value of a variable the Blueprint already declares.
Every assertion is an expression over that variables block, so they all still
mean what they meant — the part is rebuilt *and re-graded against its own
contract*. This is what a parameter slider does, and it is why the slider can
be trusted.

**Appending a feature** changes the template. The assertions the model authored
described the geometry before that operation, so they no longer describe what
comes out. The edit is still allowed — it is the user's part — but the result
is honestly a *different* Blueprint, and ``contract_broken`` says so. Silently
reporting the old verdict over new geometry would be the worst thing this
module could do.

Both paths hand the edited dict back to ``blueprint_service.build_from_payload``,
which re-runs the static checker and re-hashes before anything is built. That
means a hand edit cannot smuggle a magic number past the "no literals" rule:
new dimensions arrive as named variables, so a manually filleted part is every
bit as parametric as a generated one.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

#: A new variable has to look like one, both so it can appear in an expression
#: and so it cannot collide with the expression grammar's own names.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Operations a user can add by hand from the workbench, mapped to the
#: parameters the FreeCAD reconstruction actually reads. Anything outside this
#: set is refused by name rather than half-built: a tool that appears to work
#: and produces nothing is worse than one that says it is not wired up.
MANUAL_FEATURES = {
    "Pad",
    "Pocket",
    "Revolution",
    "Groove",
    "Hole",
    "Fillet",
    "Chamfer",
    "Draft",
    "Thickness",
    "LinearPattern",
    "PolarPattern",
    "Mirrored",
    "Loft",
    "Sweep",
}


class EditError(ValueError):
    """The edit was rejected before anything was built."""


def _finite(value: Any, where: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise EditError(f"{where}: {value!r} is not a number") from None
    if math.isnan(number) or math.isinf(number):
        raise EditError(f"{where}: {value!r} is not a finite number")
    return number


def retune(blueprint: dict, overrides: dict[str, Any]) -> dict:
    """A copy of ``blueprint`` with declared variables set to new values.

    Unknown names are refused rather than added. Adding one here would let a
    caller introduce a dimension that no assertion covers while the report still
    said VERIFIED, which is exactly the confusion this contract exists to
    prevent — use ``append_feature`` when the design really is changing.
    """
    variables = dict(blueprint.get("variables") or {})
    if not overrides:
        return dict(blueprint)

    unknown = sorted(set(overrides) - set(variables))
    if unknown:
        raise EditError(
            f"the Blueprint declares no variable named {', '.join(unknown)}"
        )

    for name, value in overrides.items():
        variables[name] = _finite(value, f"variable {name!r}")

    edited = dict(blueprint)
    edited["variables"] = variables

    # A hand-set variable *is* sourced: the user typed it. Leaving the ledger
    # alone would mean correcting a dimension the model invented did not clear
    # the warning about it, so the part stayed UNSOURCED however many numbers
    # the engineer fixed — which teaches people to ignore the label.
    plan = dict(edited.get("design_plan") or {})
    ledger = dict(plan.get("provenance") or {})
    if ledger:
        for name in overrides:
            ledger[name] = {
                "source": "stated",
                "basis": "set by hand in the workbench",
            }
        plan["provenance"] = ledger
        edited["design_plan"] = plan

    # freeze() recomputes the digest, but clearing it makes the intent explicit:
    # what comes out of here is not the thing that was hashed on the way in.
    edited["blueprint_hash"] = ""
    return edited


def _unique_id(template: dict, stem: str) -> str:
    used = {f.get("id") for f in template.get("features") or []}
    used |= {s.get("id") for s in template.get("sketches") or []}
    n = 1
    while f"{stem}{n}" in used:
        n += 1
    return f"{stem}{n}"


#: Operations that consume a profile sketch rather than dressing the existing
#: solid. Adding one of these means adding a sketch and the dependency edge
#: that binds them, or FreeCAD has nothing to extrude.
PROFILE_FEATURES = {"Pad", "Pocket", "Revolution", "Groove"}

#: Profile builders a workbench tool may draw with. Restricted to the closed,
#: single-loop shapes whose arguments are all plain scalars — the ones where a
#: small dialog can collect a complete, valid profile.
MANUAL_PROFILES = {
    "circle": ("r",),
    "rect": ("w", "h"),
    "rounded_rect": ("w", "h", "r"),
    "slot": ("length", "r"),
    "annulus": ("r_outer", "r_inner"),
    "regular_polygon": ("n", "r_circum"),
}

PLANES = {"XY", "XZ", "YZ"}


def append_feature(
    blueprint: dict,
    kind: str,
    parameters: Optional[dict[str, Any]] = None,
    variables: Optional[dict[str, Any]] = None,
    label: str = "",
    sketch: Optional[dict[str, Any]] = None,
) -> dict:
    """A copy of ``blueprint`` with one more operation on the end.

    ``variables`` are declared first so ``parameters`` — and the sketch's
    profile arguments — can refer to them by name. That indirection is
    deliberate: it is what keeps a hand-added fillet tunable afterwards instead
    of freezing a number into the template, and it is what lets the static
    checker accept the edit at all.

    ``sketch`` is required for the profile operations and refused for the
    dressups, because a fillet has no profile and silently ignoring one would
    hide a caller's mistake.
    """
    if kind not in MANUAL_FEATURES:
        raise EditError(f"{kind} cannot be added by hand yet")

    template = dict(blueprint.get("template") or {})
    features = list(template.get("features") or [])
    if not features:
        raise EditError("there is no part to add a feature to")

    declared = dict(blueprint.get("variables") or {})
    for name, value in (variables or {}).items():
        if not _NAME.match(name):
            raise EditError(f"{name!r} is not a usable variable name")
        if name in declared:
            raise EditError(f"the Blueprint already declares {name!r}")
        declared[name] = _finite(value, f"variable {name!r}")

    needs_profile = kind in PROFILE_FEATURES
    if needs_profile and not sketch:
        raise EditError(f"a {kind} needs a profile to work from")
    if sketch and not needs_profile:
        raise EditError(f"a {kind} does not take a profile")

    feature_id = _unique_id(template, kind.lower())
    new_features = [
        {
            "id": feature_id,
            "type": kind,
            "label": label or feature_id,
            "rationale": "added by hand from the workbench",
            "parameters": dict(parameters or {}),
        }
    ]

    sketches = list(template.get("sketches") or [])
    dependencies = list(template.get("dependencies") or [])

    if sketch:
        builder = sketch.get("builder")
        if builder not in MANUAL_PROFILES:
            raise EditError(f"{builder!r} is not a profile this workbench draws")
        args = dict(sketch.get("args") or {})
        missing = [a for a in MANUAL_PROFILES[builder] if a not in args]
        if missing:
            raise EditError(f"{builder} needs {', '.join(missing)}")
        plane = sketch.get("plane", "XY")
        if plane not in PLANES:
            raise EditError(f"{plane!r} is not a principal plane")

        sketch_id = _unique_id(template, "s_manual")
        sketches.append(
            {
                "id": sketch_id,
                "plane": plane,
                "profile": {"builder": builder, "args": args},
            }
        )
        # The sketch feature has to exist in the feature list *before* the
        # operation that consumes it: reconstruction walks the list in order and
        # builds the profile when it reaches it.
        new_features.insert(0, {"id": sketch_id, "type": "Sketch", "parameters": {}})
        dependencies.append(
            {"source": sketch_id, "target": feature_id, "kind": "profile"}
        )

    template["features"] = features + new_features
    template["sketches"] = sketches
    template["dependencies"] = dependencies

    edited = dict(blueprint)
    edited["template"] = template
    edited["variables"] = declared

    # Same rule as ``retune``: a dimension the engineer typed into the tool
    # dialog is stated. Recorded so a hand-built feature does not arrive
    # carrying dimensions with no entry in the ledger at all, which reads as
    # unsourced and is the opposite of what happened.
    plan = dict(edited.get("design_plan") or {})
    ledger = dict(plan.get("provenance") or {})
    if ledger:
        for name in variables or {}:
            ledger[name] = {
                "source": "stated",
                "basis": "entered by hand in the workbench",
            }
        plan["provenance"] = ledger
        edited["design_plan"] = plan

    edited["blueprint_hash"] = ""
    return edited


def template_changed(before: dict, after: dict) -> bool:
    """Whether the authored contract still describes the geometry.

    Compared on the template alone: retuning moves every measurement, but the
    assertions move with it because they are expressions over the same
    variables. Only a structural change breaks that correspondence.
    """
    from orion.blueprint import canonical_json

    try:
        return canonical_json(before.get("template")) != canonical_json(
            after.get("template")
        )
    except Exception:  # noqa: BLE001 - an unhashable edit is a changed one
        return True
