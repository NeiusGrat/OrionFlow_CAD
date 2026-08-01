"""Which path a Studio request takes, decided deterministically and on the record.

There are two ways to design a part here and they are good at different things.

The **reasoning chain** (``orion.reasoning``) works out what a part must survive
and derives every dimension from a standard or a calculation. Given a duty it
produces a specification the model cannot argue with. Given no duty it has
nothing to work from.

The **Blueprint model** turns a described part into geometry. It is excellent
when the request already carries its dimensions and unreliable when it has to
invent engineering — that is what produced a mounting plate whose bolt pattern
was sampled rather than placed.

So the question is not which is better, it is which the request is for, and that
question has to be answered *before* either runs and without asking a model.
Routing by keyword would be guesswork; routing by what the deterministic
extractor actually read is evidence.

**The rule: a load routes to the chain, and nothing else does.** A force, a
torque or a pressure is the one signal that means "size this against a duty",
and it is exactly what the chain needs to function. Dimensions do not qualify,
and neither does vocabulary — the word "bore" in *"a 30 mm central bore"* is
geometry, and reading it as a duty is how a 120x80 plate came back as a housing
for a 604 bearing. Nothing was wrong with the extractor; it was asked a question
it had no way to decline.

The failure modes are deliberately asymmetric. Sending a duty request to the
model costs the derivation that would have made it checkable. Sending a
geometry request to the chain costs the user their part and replaces it with a
question about a load they never mentioned. The second is worse, so the gate
requires positive evidence before diverting anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)

#: Duty fields that justify diverting a request to the reasoning chain. Kept in
#: step with ``orion.reasoning._LOAD_FIELDS``: the chain refuses to select
#: without one, so routing on anything weaker sends requests to a stage that can
#: only turn them away.
LOAD_FIELDS = ("radial_load_N", "axial_load_N", "torque_Nm", "pressure_bar")

#: Route names, so callers do not compare strings they invented.
CHAIN = "chain"  # orion.reasoning — sized against a duty
PRISMATIC = "prismatic"  # orion.prismatic — sized by the dimensions given
DIRECT = "direct"

#: Branches, in the order they are offered the request. Duty first: a part that
#: states a load is a duty problem even when it is plate-shaped, and the
#: prismatic branch would happily size a bracket that needed to survive
#: something it was never told about.
_BRANCHES = (CHAIN, PRISMATIC)


@dataclass
class Route:
    """Where a request is going, and the evidence that sent it there."""

    route: str
    why: str
    #: The duty the extractor read, whether or not it was enough to divert.
    duty: dict[str, Any] = field(default_factory=dict)
    #: The branch's result once it has run — a ``reasoning.Chain`` or a
    #: ``prismatic.PlateSpec``. Both expose ``complete``, ``asks()``,
    #: ``variables``, ``citations``, ``warnings``, ``to_dict()`` and
    #: ``explain()``, so callers never switch on which branch ran.
    chain: Optional[Any] = None
    #: What the Blueprint model is handed. Empty unless a branch completed.
    #: Computed here so the studio does not have to know which branch owns
    #: which ``design_prompt``.
    design_prompt: str = ""

    @property
    def to_branch(self) -> bool:
        """Whether a reasoning branch owns this request."""
        return self.route in _BRANCHES

    def to_dict(self) -> dict:
        return {"route": self.route, "why": self.why, "duty": self.duty}


def _stated_loads(duty: dict) -> list[str]:
    return [f for f in LOAD_FIELDS if duty.get(f)]


def decide(request: str) -> Route:
    """Read the request, decide the path. No model is consulted.

    Falls back to the direct route if the extractor itself raises: a router that
    can break the product when its own heuristics fail is worse than no router.
    """
    try:
        from orion import reasoning as R

        duty = dict(R.read_intent(request).detail.get("duty") or {})
    except Exception as exc:  # noqa: BLE001 — never cost a user their part
        logger.warning("design_router_intent_failed", error=repr(exc))
        return Route(
            DIRECT,
            "the duty could not be read, so the request goes " "to the model unchanged",
        )

    loads = _stated_loads(duty)
    if loads:
        return Route(
            CHAIN,
            "the request states "
            + " and ".join(_readable(f, duty[f]) for f in loads)
            + ", so the dimensions are derived before the model is asked for "
            "anything",
            duty=duty,
        )

    # No duty. A prismatic part that states its own size is still worth routing:
    # nothing has to be derived from a load, but the standards between the
    # dimensions — clearance holes, edge distance, pitch — are rules rather than
    # choices, and are exactly what the model was sampling instead of applying.
    try:
        from orion import prismatic as P

        ok, why = P.applies(request)
    except Exception as exc:  # noqa: BLE001 — never cost a user their part
        logger.warning("design_router_prismatic_failed", error=repr(exc))
        ok, why = False, "the prismatic branch could not read the request"

    if ok:
        return Route(PRISMATIC, why, duty=duty)

    return Route(
        DIRECT,
        "no load was stated and " + why + ", so the request goes to the model "
        "as written",
        duty=duty,
    )


_UNITS = {
    "radial_load_N": ("a radial load of", "N"),
    "axial_load_N": ("an axial load of", "N"),
    "torque_Nm": ("a torque of", "Nm"),
    "pressure_bar": ("a pressure of", "bar"),
}


def _readable(field_name: str, value: float) -> str:
    lead, unit = _UNITS.get(field_name, ("", ""))
    return f"{lead} {value:g} {unit}".strip()


def resolve(request: str) -> Route:
    """Decide, and on the chain route run the chain to whatever it can reach.

    A chain that stops short is still the right answer — it stopped because the
    request did not say enough, and the questions it attached are worth more
    than a part built on a number nobody supplied.
    """
    route = decide(request)
    if not route.to_branch:
        return route

    try:
        if route.route == CHAIN:
            from orion import reasoning as R

            route.chain = R.reason(request)
            if route.chain.complete:
                route.design_prompt = R.design_prompt(route.chain)
        else:
            from orion import prismatic as P

            route.chain = P.specify(request)
            if route.chain.complete:
                route.design_prompt = P.design_prompt(route.chain)
    except Exception as exc:  # noqa: BLE001
        # A branch failing is not the user's problem: fall back rather than
        # refuse, and say so in the reason so it is visible in the record.
        logger.warning(
            "design_router_branch_failed", route=route.route, error=repr(exc)
        )
        return Route(
            DIRECT,
            f"the {route.route} branch could not run, so the "
            f"request goes to the model unchanged",
            duty=route.duty,
        )
    return route
