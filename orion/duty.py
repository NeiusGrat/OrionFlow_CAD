"""Reading the duty out of a request — typed fields proposed, Python disposing.

``orion.reasoning.read_intent`` reads a duty with regular expressions, and that
is the ceiling on what this system understands about intent. Measured over eight
ordinary ways of stating a load, six were read as no duty at all::

    a manifold rated to 250 bar                    -> {}
    a flange for 16 bar working pressure           -> {}
    a bracket that must hold 50 kg                 -> {}
    a shaft carrying a load of three kilonewtons   -> {}
    a pulley driven at 1750 revolutions per minute -> {}
    a bracket taking a 200 lb side load            -> {}

Each miss is silent, and each one costs the whole derivation: a request whose
duty is not read routes to the model as a description, so nothing is sized
against anything. ``pressure_bar`` is worse than a miss — the router branches
on it and ``read_intent`` never produces one, so it was a dead field.

Reading a sentence is a language task and no amount of pattern is going to
finish it. But *deciding* on the reading is not, and this module keeps the two
apart:

**The model proposes typed fields.** One call, one flat JSON object, every field
named with its unit, and an explicit licence to omit. It never sees the route,
the calculators, or anything downstream.

**Python disposes.** A proposed value is accepted only when a number in the
request supports it, up to the unit conversions this schema declares — so "50
kg" may become 490.3 N and "three kilonewtons" may become 3000 N, but a load
nobody wrote down cannot become anything. That gate is the whole safety
argument: the failure the router most fears is a duty being *invented*, which
would divert a plain geometry request into a chain that then interrogates the
user about a load they never mentioned.

**The regex still wins where it fired.** It matched a written unit token, which
is stronger evidence than a model's reading, and keeping it authoritative means
every request that works today reads identically tomorrow.

One hole is left open and is worth stating rather than papering over: a number
written *bare* can corroborate anything. "a plate 120 x 80 x 10" would support a
proposed load of 120 N, because nothing in the text says those numerals are
lengths. Numbers carrying a unit are tagged and cannot cross (a 30 mm bore does
not support 30 N), and the extraction prompt says plainly that a dimension is
not a duty — but the gate alone does not close it. It requires the model to
invent a load that happens to equal a stated dimension, which is a much smaller
target than inventing one freely.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Optional


@dataclass(frozen=True)
class Field:
    """One duty quantity, in the unit the rest of the system stores it in."""

    name: str
    unit: str
    ask: str
    #: Multipliers that carry a number as a user might write it into ``unit``.
    #: Also the only conversions the corroboration gate will credit — a value
    #: that is not some stated number times one of these is not supported.
    factors: tuple[float, ...] = (1.0,)


#: The duty schema. Names match ``orion.reasoning.read_intent``'s keys exactly,
#: because a field under a new name would be read here and ignored everywhere.
FIELDS: tuple[Field, ...] = (
    Field("radial_load_N", "N",
          "force acting across the axis (radial, transverse, side load)",
          (1.0, 1000.0, 4.4482216, 9.80665)),
    Field("axial_load_N", "N",
          "force acting along the axis (axial, thrust, end load)",
          (1.0, 1000.0, 4.4482216, 9.80665)),
    Field("torque_Nm", "Nm", "torque or moment",
          (1.0, 1000.0, 1.3558179, 9.80665)),
    Field("pressure_bar", "bar", "working or rated fluid pressure",
          (1.0, 0.0689476, 0.01, 10.0, 1e-5)),
    Field("speed_rpm", "rpm", "rotational speed",
          (1.0, 60.0)),
    Field("life_hours", "h", "required service life",
          (1.0, 8760.0, 24.0)),
    Field("bore_mm", "mm", "shaft, journal or bore diameter it fits",
          (1.0, 25.4, 10.0)),
    Field("misalignment_deg", "deg", "angular misalignment it must tolerate"),
    Field("max_outside_dia_mm", "mm", "largest outside diameter it may occupy",
          (1.0, 25.4, 10.0)),
)

BY_NAME = {f.name: f for f in FIELDS}


@dataclass
class Duty:
    """What one extraction read, and why it could not be trusted where it was."""

    fields: dict[str, float] = dc_field(default_factory=dict)
    #: Values the model proposed that no number in the request supports. Kept
    #: rather than dropped: a duty the model invented is worth logging, and
    #: silently discarding it makes the gate impossible to observe.
    rejected: dict[str, float] = dc_field(default_factory=dict)
    notes: list[str] = dc_field(default_factory=list)
    transport_error: str = ""


#: What the model is asked. Generated from the schema so a field added above is
#: asked for without touching a prompt, and the two cannot drift.
def extract_prompt() -> str:
    lines = "\n".join(f"  {f.name}   ({f.unit}) — {f.ask}" for f in FIELDS)
    return f"""You are OrionFlow's Duty Extractor.

Read the request and report the engineering duty it states. Nothing else — you \
are not designing anything and you will not see the result.

Report these fields, converted to the unit shown:

{lines}

Rules:
- Convert to the stated unit. 3 kN is 3000 N; 50 kg of load is 490.3 N; 200 lb \
is 889.6 N; 1750 revolutions per minute is 1750 rpm; 25 Hz is 1500 rpm; \
5 years is 43800 h; 250 psi is 17.2 bar.
- Omit any field the request does not state. Omission is the correct answer far \
more often than a value is.
- Never estimate, never default, never infer a typical value for the kind of \
part being described. A number that is not in the request must not appear in \
your answer. A load you supply will be checked against the request and thrown \
away.
- A dimension is not a duty. "a 30 mm bore" states bore_mm; it does not state a \
load.

Answer with one flat JSON object and no prose. {{}} is a valid answer."""


#: Completion budget. One small extraction; the retry exists for a reasoning
#: model that spends the first budget deriving and emits the JSON last, exactly
#: as in ``orion.interview``.
READ_TOKENS = int(os.environ.get("ORION_DUTY_TOKENS", "1024"))
REASONING_TOKENS = int(os.environ.get("ORION_DUTY_REASONING_TOKENS", "4096"))


def _json_of(text: str) -> Optional[dict]:
    """The first JSON object in a completion, or None."""
    body = text or ""
    start = body.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(body)):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(body[start:i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


#: Fields that *are* lengths, and may therefore be supported by a length.
_LENGTH_FIELDS = frozenset({"bore_mm", "max_outside_dia_mm"})

#: Tolerance when matching a converted value back against what was written.
#:
#: Not ``provenance``'s 1e-6. That tolerance is right for a dimension, where the
#: number in the Blueprint is the number the user typed. Here the model has
#: done arithmetic and will round it: 50 kg came back as 490.3 N, which is
#: 49.9966 kg — outside 1e-6 and plainly the same statement. One percent is
#: loose enough for any sane rounding and far too tight to confuse 200 with 250.
REL_TOL = 0.01


def supported(name: str, value: Any, literals: list) -> bool:
    """Whether a number in the request accounts for this proposed value.

    The gate. A value counts when it is some stated number times one of the
    conversions this field declares — which credits an honest unit change and
    refuses a figure that was not written down anywhere.

    A number written as a length supports only a length. Without that, "a 30 mm
    bore housing" states a literal 30, and 30 N would be accepted as a duty the
    request never gave — the exact invention this gate exists to stop, arriving
    through the front door.
    """
    spec = BY_NAME.get(name)
    if spec is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    from . import provenance as P

    pool = [
        number
        for number, unit in literals
        if name in _LENGTH_FIELDS or unit not in P.LENGTH_UNITS
    ]
    if not pool:
        return False
    for factor in spec.factors:
        if factor and P.corroborated(float(value) / factor, pool, rel_tol=REL_TOL):
            return True
    return False


def read(client, request: str, max_tokens: int = READ_TOKENS) -> Duty:
    """One extraction call, gated. Never raises — a dead endpoint is a note."""
    from orion_agent.harness.llm.base import LLMMessage

    msgs = [LLMMessage.system(extract_prompt()), LLMMessage.user(request)]

    def once(budget: int):
        resp = client.chat(msgs, max_tokens=budget, temperature=0.0)
        if getattr(resp, "finish_reason", "") == "error":
            return resp, (resp.content or "the model could not be reached")
        return resp, ""

    try:
        resp, dead = once(max_tokens)
        if not dead and not (resp.content or "").strip() and max_tokens < REASONING_TOKENS:
            resp, dead = once(REASONING_TOKENS)
    except Exception as exc:  # noqa: BLE001 — an outage is not a duty
        return Duty(transport_error=str(exc))
    if dead:
        return Duty(transport_error=dead)

    return gate(request, _json_of(resp.content) or {})


def gate(request: str, proposed: dict) -> Duty:
    """Keep the proposed fields the request actually supports. No model here."""
    from . import provenance as P

    literals = P.literals_with_units(request)
    out = Duty()
    for name, raw in (proposed or {}).items():
        if name not in BY_NAME:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0 and name != "misalignment_deg":
            continue
        if supported(name, value, literals):
            out.fields[name] = value
        else:
            out.rejected[name] = value
            out.notes.append(
                f"{name}={value:g} was proposed but no number in the request "
                f"supports it, so it was not used"
            )
    return out


def merge(read_by_pattern: dict, proposed: Duty) -> tuple[dict, list[str]]:
    """``(duty, notes)`` — the pattern reading, extended by the gated one.

    The pattern reading is authoritative wherever it fired: it matched a unit
    token that is literally in the request, which is stronger evidence than a
    model's interpretation of the same sentence. The model only fills fields the
    patterns left empty, which is the whole of the improvement and none of the
    risk — every request that routes correctly today routes identically.
    """
    duty = dict(read_by_pattern or {})
    notes = list(proposed.notes)
    for name, value in proposed.fields.items():
        if name in duty:
            if abs(duty[name] - value) > 1e-6 * max(1.0, abs(duty[name])):
                notes.append(
                    f"{name}: read {duty[name]:g} from the units in the request; "
                    f"a second reading said {value:g}. Kept the first."
                )
            continue
        duty[name] = value
        notes.append(f"{name}={value:g} read from the request wording")
    return duty, notes
