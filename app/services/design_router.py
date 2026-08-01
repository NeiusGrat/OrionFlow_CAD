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
CHAIN = "chain"
DIRECT = "direct"


@dataclass
class Route:
    """Where a request is going, and the evidence that sent it there."""

    route: str
    why: str
    #: The duty the extractor read, whether or not it was enough to divert.
    duty: dict[str, Any] = field(default_factory=dict)
    #: Set only on the chain route, once the chain has run.
    chain: Optional[Any] = None

    @property
    def to_chain(self) -> bool:
        return self.route == CHAIN

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
    if not loads:
        return Route(
            DIRECT,
            "no load, torque or pressure was stated, so there is no duty to "
            "size against — the request is read as geometry",
            duty=duty,
        )

    return Route(
        CHAIN,
        "the request states "
        + " and ".join(_readable(f, duty[f]) for f in loads)
        + ", so the dimensions are derived before the model is asked for "
        "anything",
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
    if not route.to_chain:
        return route

    try:
        from orion import reasoning as R

        route.chain = R.reason(request)
    except Exception as exc:  # noqa: BLE001
        # The chain failing is not the user's problem: fall back rather than
        # refuse, and say so in the reason so it is visible in the record.
        logger.warning("design_router_chain_failed", error=repr(exc))
        return Route(
            DIRECT,
            "the reasoning chain could not run, so the "
            "request goes to the model unchanged",
            duty=route.duty,
        )
    return route
