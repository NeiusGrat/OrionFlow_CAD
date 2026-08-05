"""Editing a part by pointing at it.

The topology layer answers *what is this?* — a click resolves to the Blueprint
feature that authored the face. This is the other half: *change it, and keep the
design's meaning intact.*

The gap it closes is small and specific. ``blueprint_edit.retune`` sets
**variables**; a user clicking a fillet wants to change **a radius**. Nothing
connected the two, because the connection is not stored anywhere — it has to be
read out of the template, where a feature's parameter is an *expression* over
the variables block.

Three things make that harder than a dictionary lookup, and all three are the
reason this module exists rather than being three lines in the route.

**A dimension often lives in the sketch, not the feature.** A bore's depth is
``Pocket.Length``, but its *radius* is the ``r`` argument of the profile sketch
the pocket consumes, reached through a ``profile`` dependency edge. A user
clicking the bore wall and asking for "radius" means the sketch. So the editable
surface of a feature includes the profile it was cut with.

**Changing one number moves others, and that is the design working.** If ``t``
drives both the plate thickness and the depth of a through-cut, retuning it
moves both — that is the parametric intent, not a bug. A direct-modelling tool
would break the link silently. Here every edit is planned first and reports
exactly what else moves, so the linkage is visible before it is committed rather
than discovered afterwards.

**An expression is not invertible in general.** When a parameter is ``t * 2``,
there is no honest way to "set it to 14" — the module refuses and names the
variables that would have to change instead. Solving numerically for one of them
would produce a part the user did not ask for, from a number they never typed.

Intent survives because a retune is a change of *value*, never of structure: the
assertions are expressions over the same variables, so they still mean what they
meant and the rebuilt part is re-graded against its own contract. Anything that
would change the template is not reachable from here — that is
``blueprint_edit.append_feature``, and it says the contract is broken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from orion import expr as E

#: Parameters that carry a value but not a *dimension*: enums, mode flags, and
#: the selector strings that say which edges a dressup lands on. Editable in
#: principle, but not by dragging a number, so they are reported as read-only
#: with a reason rather than silently omitted.
from orion.blueprint import _ENUM_PARAMS as ENUM_PARAMS


class EditError(ValueError):
    """The edit was rejected before anything was built."""


@dataclass(frozen=True)
class Site:
    """One place an expression appears in a Blueprint.

    ``owner`` is a feature id or a sketch id; ``key`` is the parameter or
    profile-argument name. Together they are what a plan reports as moving.
    """

    kind: str  # "feature" | "sketch"
    owner: str
    key: str
    expression: str

    @property
    def path(self) -> str:
        return f"{self.owner}.{self.key}"


@dataclass
class Parameter:
    """An editable dimension of a feature, as a user would think of it."""

    name: str  # "Radius", or "profile.r" for a dimension held in the sketch
    site: Site
    value: float
    variables: list[str]
    #: True when the expression is exactly one variable, so setting the value
    #: and setting the variable are the same act. Only these are directly
    #: editable; anything else is a computed dimension.
    direct: bool
    #: Other places the same variables drive. Empty means this number is the
    #: feature's alone.
    shared_with: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expression": self.site.expression,
            "value": self.value,
            "variables": self.variables,
            "direct": self.direct,
            "variable": self.variables[0] if self.direct else None,
            "shared_with": self.shared_with,
        }


@dataclass
class Move:
    """One number that changes as a consequence of an edit."""

    path: str
    expression: str
    before: float
    after: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "expression": self.expression,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class Plan:
    """What an edit would do, decided before anything is built."""

    feature: str
    parameter: str
    variable: str
    before: float
    after: float
    #: Everything else that moves. The point of planning: a parametric design
    #: ties dimensions together on purpose, and the user should see the tie
    #: before committing to it, not infer it from the result.
    also_moves: list[Move] = field(default_factory=list)
    #: Assertions whose evaluated target shifts. They still *hold* — they are
    #: expressions over the same variables — but the numbers they check against
    #: are different, and a report that did not say so would look like the
    #: contract had been weakened.
    assertions_moved: list[Move] = field(default_factory=list)

    @property
    def contract_preserved(self) -> bool:
        """A retune never changes the template, so the contract always survives.

        Stated as a property rather than a stored flag so it cannot drift out of
        step with what the plan actually does.
        """
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "parameter": self.parameter,
            "variable": self.variable,
            "before": self.before,
            "after": self.after,
            "also_moves": [m.as_dict() for m in self.also_moves],
            "assertions_moved": [m.as_dict() for m in self.assertions_moved],
            "contract_preserved": self.contract_preserved,
        }


# --------------------------------------------------------------------------- #
# reading the template
# --------------------------------------------------------------------------- #
def _template(blueprint: dict) -> dict:
    template = blueprint.get("template")
    if not isinstance(template, dict):
        raise EditError("this part has no Blueprint template to edit")
    return template


def _features(blueprint: dict) -> list[dict]:
    return [f for f in (_template(blueprint).get("features") or []) if f.get("id")]


def _sketches(blueprint: dict) -> dict[str, dict]:
    return {
        s["id"]: s for s in (_template(blueprint).get("sketches") or []) if s.get("id")
    }


def profile_of(blueprint: dict, feature_id: str) -> Optional[str]:
    """The sketch a feature consumes, via the ``profile`` dependency edge.

    This is what makes "the bore's radius" reachable: the number is an argument
    of the sketch, and only this edge says which sketch belongs to which cut.
    """
    for edge in _template(blueprint).get("dependencies") or []:
        if edge.get("kind") == "profile" and edge.get("target") == feature_id:
            return edge.get("source")
    return None


def _is_expression(key: str, value: Any) -> bool:
    """Whether a parameter carries a dimension rather than a mode or a selector."""
    return isinstance(value, str) and not key.startswith("_") and key not in ENUM_PARAMS


def sites(blueprint: dict) -> Iterator[Site]:
    """Every place an expression appears, features and sketches alike.

    One traversal, used by both the editable surface and the impact analysis, so
    the two can never disagree about where a variable is used.
    """
    for feature in _features(blueprint):
        for key, value in (feature.get("parameters") or {}).items():
            if _is_expression(key, value):
                yield Site("feature", feature["id"], key, value)

    for sketch_id, sketch in _sketches(blueprint).items():
        args = ((sketch.get("profile") or {}).get("args")) or {}
        for key, value in args.items():
            if isinstance(value, str):
                yield Site("sketch", sketch_id, key, value)


def _evaluate(expression: str, variables: dict) -> Optional[float]:
    try:
        return E.evaluate(expression, variables)
    except (E.ExprError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# what a click can change
# --------------------------------------------------------------------------- #
def editable(blueprint: dict, feature_id: str) -> list[Parameter]:
    """The dimensions of one feature, as a user would think of them.

    Includes the profile sketch's arguments under a ``profile.`` prefix, because
    a bore's radius is a property of the bore to everyone except the file
    format.
    """
    variables = dict(blueprint.get("variables") or {})
    known = {f["id"] for f in _features(blueprint)}
    if feature_id not in known:
        raise EditError(
            f"no feature {feature_id!r} in this Blueprint; it has {sorted(known)}"
        )

    sketch_id = profile_of(blueprint, feature_id)
    usage = _usage(blueprint)

    out: list[Parameter] = []
    for site in sites(blueprint):
        if site.kind == "feature" and site.owner == feature_id:
            name = site.key
        elif site.kind == "sketch" and site.owner == sketch_id:
            name = f"profile.{site.key}"
        else:
            continue

        value = _evaluate(site.expression, variables)
        if value is None:
            continue

        names = sorted(E.names(site.expression) & set(variables))
        direct = site.expression.strip() in variables
        shared = sorted({p for v in names for p in usage.get(v, set())} - {site.path})
        out.append(
            Parameter(
                name=name,
                site=site,
                value=value,
                variables=names,
                direct=direct,
                shared_with=shared,
            )
        )

    out.sort(key=lambda p: (not p.direct, p.name))
    return out


def _usage(blueprint: dict) -> dict[str, set[str]]:
    """variable -> the paths that depend on it."""
    variables = set(blueprint.get("variables") or {})
    usage: dict[str, set[str]] = {}
    for site in sites(blueprint):
        for name in E.names(site.expression) & variables:
            usage.setdefault(name, set()).add(site.path)
    return usage


def impact(blueprint: dict, variable: str) -> dict[str, Any]:
    """Everything one variable drives — the honest answer to "what if I change this?".

    Assertion sites are reported separately from geometry sites. A moved
    assertion target is not a weakened contract: the check is an expression over
    the same variables, so it moves with the part it grades. Conflating the two
    would make a correct parametric design look like it had lost its guarantees.
    """
    variables = dict(blueprint.get("variables") or {})
    if variable not in variables:
        raise EditError(f"the Blueprint declares no variable named {variable!r}")

    geometry = sorted(_usage(blueprint).get(variable, set()))
    assertions = [
        a.get("id") or a.get("kind") or "?"
        for a in blueprint.get("assertions") or []
        if any(
            variable in E.names(a[key])
            for key in ("target", "lo", "hi")
            if isinstance(a.get(key), str)
        )
    ]
    return {
        "variable": variable,
        "value": variables[variable],
        "drives": geometry,
        "assertions": assertions,
    }


# --------------------------------------------------------------------------- #
# planning an edit
# --------------------------------------------------------------------------- #
def plan(blueprint: dict, feature_id: str, parameter: str, value: float) -> Plan:
    """Decide what setting ``parameter`` to ``value`` would do. Builds nothing.

    Refuses a computed dimension rather than solving for it. ``t * 2`` cannot be
    "set to 14" without choosing a value for ``t`` that the user never typed, and
    a part built from an invented number is worse than a refusal that names the
    variable to edit instead.
    """
    try:
        target = float(value)
    except (TypeError, ValueError):
        raise EditError(f"{value!r} is not a number") from None
    if target != target or target in (float("inf"), float("-inf")):
        raise EditError(f"{value!r} is not a finite number")

    candidates = editable(blueprint, feature_id)
    match = next((p for p in candidates if p.name == parameter), None)
    if match is None:
        raise EditError(
            f"{feature_id} has no editable parameter {parameter!r}; "
            f"it has {[p.name for p in candidates]}"
        )

    if not match.direct:
        raise EditError(
            f"{feature_id}.{parameter} is computed from "
            f"{' and '.join(match.variables) or 'no variable'} "
            f"({match.site.expression!r}) and cannot be set directly — "
            f"edit {' or '.join(match.variables) or 'the design'} instead"
        )

    variable = match.variables[0]
    variables = dict(blueprint.get("variables") or {})
    before = variables[variable]

    after_vars = dict(variables)
    after_vars[variable] = target

    also = []
    for site in sites(blueprint):
        if variable not in E.names(site.expression):
            continue
        was = _evaluate(site.expression, variables)
        now = _evaluate(site.expression, after_vars)
        if was is None or now is None or was == now:
            continue
        if site.path == match.site.path:
            continue
        also.append(Move(site.path, site.expression, was, now))

    moved_assertions = []
    for assertion in blueprint.get("assertions") or []:
        for key in ("target", "lo", "hi"):
            text = assertion.get(key)
            if not isinstance(text, str) or variable not in E.names(text):
                continue
            was = _evaluate(text, variables)
            now = _evaluate(text, after_vars)
            if was is None or now is None or was == now:
                continue
            label = assertion.get("id") or assertion.get("kind") or "?"
            moved_assertions.append(Move(f"{label}.{key}", text, was, now))

    also.sort(key=lambda m: m.path)
    return Plan(
        feature=feature_id,
        parameter=parameter,
        variable=variable,
        before=before,
        after=target,
        also_moves=also,
        assertions_moved=moved_assertions,
    )


def apply(blueprint: dict, edit: Plan) -> dict:
    """The edited Blueprint. A retune, so ``blueprint_edit`` owns the mechanics.

    Routed through ``retune`` rather than writing the variables block here on
    purpose: that function is what refuses undeclared names and non-finite
    values, and a second path into the variables block would be a second place
    for those rules to be forgotten.
    """
    from app.services import blueprint_edit

    return blueprint_edit.retune(blueprint, {edit.variable: edit.after})
