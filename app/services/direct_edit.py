"""Applying a CAD operation to geometry the user pointed at.

``semantic_edit`` changes a *value* a feature already declares. This adds a
feature that was not there — chamfer this edge, pocket this face — which is a
different act with a different honesty requirement, and the two are kept apart
for exactly that reason.

**A retune preserves the contract. This does not.** The assertions a design was
authored with describe the geometry *before* the new operation, so after it they
no longer describe the part. The edit is still the user's to make — it is their
part — but the verdict that comes back is a grade of a design the model never
authored, and ``contract_broken`` says so. Reporting the old verdict over new
geometry would be the worst thing this module could do, and it is the one thing
it is built to prevent.

**Naming the geometry is the hard part.** A person clicked one edge. Every
selector in the authored grammar names a *class* — all vertical edges, every rim
of radius 5 — which is right for "break all the corners" and useless here. An
OCC index would name the right edge today and a different one after any rebuild
that shifts numbering.

So the click is recorded as ``near:<x>,<y>,<z>``: the edge whose midpoint is
closest to a point. That is a statement about geometry rather than about
FreeCAD's numbering, so it survives a rebuild, and when the edit moves the edge
beyond the tolerance the selector resolves to nothing and the build fails
visibly rather than quietly dressing the wrong edge.

**Dimensions arrive as variables, never literals.** A hand-added 2 mm chamfer
declares a variable and refers to it, so the result is as parametric as a
generated part and the static checker accepts it. That is enforced downstream by
``blueprint_edit.append_feature``; this module only decides what to hand it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: Operations reachable by pointing at geometry, and what each needs.
#:
#: ``target`` is what the user must have selected; ``dimensions`` are the
#: numbers the dialog collects, in the order they should be shown. Anything not
#: listed here is refused by name rather than half-built — a tool that appears
#: to work and produces nothing is worse than one that says it is not wired up.
OPERATIONS: dict[str, dict[str, Any]] = {
    "Chamfer": {
        "target": "edge",
        "dimensions": [
            {
                "name": "Size",
                "label": "Distance",
                "unit": "mm",
                "default": 1.0,
                "min": 0.01,
            }
        ],
        "blurb": "Break a selected edge at 45 degrees.",
    },
    "Fillet": {
        "target": "edge",
        "dimensions": [
            {
                "name": "Radius",
                "label": "Radius",
                "unit": "mm",
                "default": 2.0,
                "min": 0.01,
            }
        ],
        "blurb": "Round a selected edge.",
    },
    "Draft": {
        "target": "face",
        "dimensions": [
            {
                "name": "Angle",
                "label": "Draft angle",
                "unit": "deg",
                "default": 2.0,
                "min": 0.1,
                "max": 45.0,
            }
        ],
        "blurb": "Taper a selected face for moulding release.",
    },
    "Thickness": {
        "target": "face",
        "dimensions": [
            {
                "name": "Value",
                "label": "Wall",
                "unit": "mm",
                "default": 2.0,
                "min": 0.05,
            }
        ],
        "blurb": "Hollow the solid, opening the selected face.",
    },
}

#: Operations the workbench will offer once they have a profile story. Listed
#: so the UI can show them as coming rather than pretend they do not exist, and
#: so the reason each is not here is written down.
PLANNED: dict[str, str] = {
    "Hole": "needs a position on the selected face and a standard drill table",
    "Pocket": "needs a profile sketched on the selected face",
    "Boss": "needs a profile sketched on the selected face",
    "Rib": "needs a path and a thickening direction",
    "Pattern": "needs a direction and count relative to an existing feature",
    "Mirror": "needs a mirror plane chosen from the part's datums",
}

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DirectEditError(ValueError):
    """The operation was rejected before anything was built."""


@dataclass
class Operation:
    """A proposed feature, decided before the kernel is touched."""

    kind: str
    target_kind: str  # "edge" | "face"
    selector: str  # near:<x>,<y>,<z>
    #: The feature the selected geometry belongs to. Not used to build — the
    #: selector does that — but reported so the user can see what they aimed at.
    on_feature: Optional[str]
    variables: dict[str, float] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target_kind": self.target_kind,
            "selector": self.selector,
            "on_feature": self.on_feature,
            "variables": self.variables,
            "parameters": self.parameters,
            "label": self.label,
            # Always true here, and stated rather than left to be inferred: a
            # new feature puts the geometry outside what the authored
            # assertions describe.
            "contract_broken": True,
        }


def catalogue() -> dict[str, Any]:
    """What the workbench can do, and what it cannot do yet."""
    return {
        "operations": [{"kind": kind, **spec} for kind, spec in OPERATIONS.items()],
        "planned": [{"kind": k, "reason": v} for k, v in PLANNED.items()],
    }


def _unique_variable(blueprint: dict, stem: str) -> str:
    declared = set(blueprint.get("variables") or {})
    if stem not in declared:
        return stem
    n = 2
    while f"{stem}{n}" in declared:
        n += 1
    return f"{stem}{n}"


#: Feature types that leave a solid behind for the next operation to work on.
#: Mirrors the vocabulary ``freecad/reconstruct.py`` records in ``built_solids``.
_SOLID_TYPES = {
    "Pad",
    "Pocket",
    "Revolution",
    "Groove",
    "Hole",
    "Loft",
    "Sweep",
    "Fillet",
    "Chamfer",
    "Draft",
    "Thickness",
    "LinearPattern",
    "PolarPattern",
    "Mirrored",
}


def _tip_feature(blueprint: dict) -> Optional[str]:
    """The last feature that leaves a solid — what a new operation attaches to."""
    template = blueprint.get("template") or {}
    for feature in reversed(template.get("features") or []):
        if feature.get("type") in _SOLID_TYPES and feature.get("id"):
            return feature["id"]
    return None


def _finite(value: Any, where: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DirectEditError(f"{where}: {value!r} is not a number") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise DirectEditError(f"{where}: {value!r} is not a finite number")
    return number


def selector_for(element: dict) -> str:
    """The ``near:`` selector naming one picked edge or face.

    Built from the element's own recorded centroid rather than from the raw
    click, so the point is exactly on the geometry the topology layer resolved.
    A raycast hit is a few tenths of a millimetre off whatever it struck; the
    centroid is not, and the difference decides whether a later rebuild still
    finds the same edge.
    """
    centre = element.get("center")
    if not centre or len(centre) != 3:
        raise DirectEditError(
            "that geometry has no recorded position, so it cannot be named"
        )
    return "near:%s" % ",".join(f"{float(c):.6g}" for c in centre)


def plan(
    blueprint: dict,
    kind: str,
    element: dict,
    dimensions: dict[str, Any],
) -> Operation:
    """Decide the feature to add. Builds nothing, touches no kernel.

    ``element`` is a topology record — the face or edge the user picked.
    """
    spec = OPERATIONS.get(kind)
    if spec is None:
        if kind in PLANNED:
            raise DirectEditError(f"{kind} is not wired up yet: {PLANNED[kind]}")
        raise DirectEditError(f"{kind} is not an operation this workbench has")

    wanted = spec["target"]
    got = (
        "edge"
        if str(element.get("ref", "")).rsplit(".", 1)[-1].startswith("e")
        else "face"
    )
    if wanted != got:
        raise DirectEditError(
            f"a {kind} is applied to an {wanted}; you selected a {got}"
        )

    selector = selector_for(element)

    variables: dict[str, float] = {}
    parameters: dict[str, Any] = {}
    for dim in spec["dimensions"]:
        name = dim["name"]
        if name not in dimensions:
            raise DirectEditError(f"a {kind} needs {dim['label'].lower()}")
        value = _finite(dimensions[name], dim["label"])
        low = dim.get("min")
        high = dim.get("max")
        if low is not None and value < low:
            raise DirectEditError(
                f"{dim['label'].lower()} must be at least {low}{dim['unit']}"
            )
        if high is not None and value > high:
            raise DirectEditError(
                f"{dim['label'].lower()} must be at most {high}{dim['unit']}"
            )

        # A number typed into a dialog becomes a named variable, so the added
        # feature stays tunable afterwards and the no-literals rule still holds.
        stem = f"{kind.lower()}_{name.lower()}"
        variable = _unique_variable(blueprint, stem)
        if not _NAME.match(variable):
            raise DirectEditError(f"{variable!r} is not a usable variable name")
        variables[variable] = value
        parameters[name] = variable

    if wanted == "edge":
        parameters["_Edges"] = selector
    else:
        parameters["_Faces"] = selector

    # Fillet, Chamfer and Draft fall back to the tip solid when no base is
    # named, which is what a hand-added dressup wants. Thickness does not — it
    # reports "missing thickness base" and builds nothing — so the tip is named
    # for it explicitly rather than left to a fallback that is not there.
    if kind == "Thickness":
        base = _tip_feature(blueprint)
        if base is None:
            raise DirectEditError("there is no solid to hollow yet")
        parameters["_Base"] = {"object": base}

    if kind == "Draft":
        # A draft pivots the tapered face about a neutral plane, and the
        # compiler defaults that to "bottom". Drafting the bottom face itself
        # then asks the face to pivot about itself, which OCC rejects with
        # "invalid after recompute" — observed, and silent until the build
        # check above started reading the kernel's report.
        #
        # A face is drafted about the plane at the *other* end of the pull
        # direction, so the neutral plane is chosen opposite the selection.
        normal = element.get("normal") or [0.0, 0.0, 0.0]
        if len(normal) == 3 and abs(normal[2]) > 0.8:
            parameters["_NeutralPlane"] = "bottom" if normal[2] > 0 else "top"
        else:
            # A vertical wall drafts about the bottom, which is the mould-release
            # convention and what the compiler would have picked anyway.
            parameters["_NeutralPlane"] = "bottom"

    return Operation(
        kind=kind,
        target_kind=wanted,
        selector=selector,
        on_feature=element.get("feature"),
        variables=variables,
        parameters=parameters,
        label=f"{kind} on {element.get('stable') or element.get('ref')}",
    )


def added_feature_id(edited: dict) -> Optional[str]:
    """The id ``append_feature`` gave the new operation.

    It generates the id internally (``chamfer1``, ``fillet2``) and appends the
    operation last, so the last feature in the edited template is the one that
    was just added. Needed because the caller has to be able to ask whether
    *that* feature built.
    """
    features = (edited.get("template") or {}).get("features") or []
    return features[-1].get("id") if features else None


def build_failure(bundle: dict, feature_id: Optional[str]) -> Optional[str]:
    """Why the requested operation did not build, or None if it did.

    **The bug this exists to prevent.** ``bundle["success"]`` means the build
    produced a downloadable solid with a measurable volume — it says nothing
    about whether the feature the user asked for is *in* that solid. A Draft
    that fails to recompute leaves the previous geometry intact, so the build
    succeeds, the volume is unchanged, the assertions still pass, and the user
    is told their operation worked when nothing happened.

    That was observed: a Draft reported ``invalid after recompute`` and a
    Thickness reported ``missing thickness base``, and both commits returned
    ``success: true, verdict: verified``. The kernel had said exactly what went
    wrong and the route threw it away.
    """
    if not feature_id:
        return None
    report = ((bundle.get("build_log") or {}).get("build_report")) or {}

    for entry in report.get("recompute_errors") or []:
        if entry.get("id") == feature_id:
            return str(entry.get("error") or "the operation did not build")

    for entry in report.get("unsupported") or []:
        if entry.get("id") == feature_id:
            return f"{entry.get('type', 'that operation')} is not supported by the compiler"

    # Nothing built at all is already reported through ``error``; only claim a
    # per-feature failure when the build otherwise succeeded.
    built = {b.get("id") for b in report.get("built") or []}
    if built and feature_id not in built:
        return "the operation was not applied — the kernel did not report it as built"
    return None


def apply(blueprint: dict, operation: Operation) -> dict:
    """The edited Blueprint, with the new feature appended.

    Routed through ``blueprint_edit.append_feature`` rather than editing the
    template here: that function owns the rules about variable names, unique
    feature ids and which operations may be added by hand, and a second path
    into the template would be a second place for them to be forgotten.
    """
    from app.services import blueprint_edit

    return blueprint_edit.append_feature(
        blueprint,
        operation.kind,
        parameters=operation.parameters,
        variables=operation.variables,
        label=operation.label,
    )
