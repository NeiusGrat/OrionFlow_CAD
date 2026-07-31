"""The handoff from engineering reasoning to the Blueprint model.

This is the one place where an orchestration layer is allowed to touch the
design prompt, and it exists to make that touching safe.

The temptation is to hand the Blueprint model a rich specification object —
standards cited, loads computed, fits chosen, tolerances resolved — because all
of that is genuinely known by the time we call it. Doing so would cost the
number the whole system is built on. The adapter was trained on exactly two
input shapes and nothing else:

    spec    "Design a parametric gusset plate.
             Variables: a=106, b=56, t=6
             Every dimension must be an expression over the variables; state
             the volume you expect and why."

    diverse "We need a gusset plate for a jig. It should be 6 mm thick. Make it
             fully parametric and tell me the expected volume."

A JSON specification is neither. So the rule here is: **engineering decides the
numbers; it never changes the sentence.** Everything the planner learned that is
not a variable travels *beside* the call — available to the conversation role,
shown to the user, logged for training — and never enters the design prompt.

The renderer does not reimplement the grammar. It calls
``orion.pack_sft.spec_prompt``, the same function that built the training set,
so byte-identity is structural rather than something a test has to keep
rediscovering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)


class SpecError(ValueError):
    """The specification cannot be rendered into a prompt the model understands."""


@dataclass
class EngineeringSpecification:
    """What the planner decided, split by what the model may see.

    ``part_class`` and ``variables`` are the *only* fields that reach the model.
    The rest is provenance: it explains the numbers to a human, feeds the
    conversation role, and gives a future training run something to learn the
    reasoning from — without any of it perturbing the design turn today.
    """

    part_class: str
    variables: dict[str, float]

    #: Optional single lines the trained ``spec`` view already supports. Present
    #: in the grammar, so safe; still omitted unless the planner has something
    #: real to say, because an empty line is a changed prompt.
    function: str = ""
    manufacturing: str = ""

    # ---- provenance: never rendered ------------------------------------- #
    #: variable name -> why it has this value ("ISO 273 normal clearance for M8")
    rationale: dict[str, str] = field(default_factory=dict)
    #: standards, clauses, catalogue parts the planner consulted
    citations: list[str] = field(default_factory=list)
    #: calculator outputs backing the numbers, keyed by calculator name
    calculations: dict[str, Any] = field(default_factory=dict)
    #: constraints the planner honoured but could not express as a variable
    constraints: list[str] = field(default_factory=list)
    material: str = ""
    process: str = ""

    # ------------------------------------------------------------------ #
    def validate(self) -> list[str]:
        """Problems that would produce a broken Blueprint. Empty list is clean.

        Deliberately catches the two failures a planner is most likely to cause
        and that are invisible until much later:

        * a non-finite or non-numeric value, which the expression layer cannot
          evaluate and which surfaces as a confusing freeze error;
        * a variable named after a built-in function or constant. ``max``,
          ``min``, ``abs``, ``pi`` resolve to the function, so every reference
          reads as an unknown name and the variable itself looks unused. The
          static checker rejects this after the fact; catching it here means the
          planner is told, not the model blamed.
        """
        from orion import expr as E

        problems: list[str] = []
        if not self.part_class or not self.part_class.strip():
            problems.append("part_class is empty")
        if not self.variables:
            problems.append("no variables — the model would have nothing to "
                            "express dimensions over")

        for name, value in self.variables.items():
            if not isinstance(name, str) or not name.isidentifier():
                problems.append(f"variable {name!r} is not a valid identifier")
                continue
            if name in E.FUNCTIONS or name in E.CONSTANTS:
                kind = "function" if name in E.FUNCTIONS else "constant"
                problems.append(
                    f"variable {name!r} shadows the built-in {kind} {name!r} — "
                    f"every reference to it would resolve to the {kind}; "
                    f"rename it")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"variable {name!r} is {value!r}, not a number")
            elif not math.isfinite(float(value)):
                problems.append(f"variable {name!r} is {value!r}")
        return problems

    # ------------------------------------------------------------------ #
    def warnings(self) -> list[str]:
        """Schema drift: real, but not fatal, so it never blocks a render.

        :func:`orion.family_schema.check` compares the planned variables against
        what the family actually carried in training — missing names, invented
        names, values outside the observed region. A planner is allowed to leave
        that region deliberately; it should not leave it by accident, and the
        difference between those two is whether anyone was told.
        """
        from orion.family_schema import check

        notes = check(self.part_class, self.variables)
        unfamiliar = looks_unfamiliar(self.part_class)
        if unfamiliar:
            notes.append(unfamiliar)
        return notes

    # ------------------------------------------------------------------ #
    def to_prompt(self) -> str:
        """Render into the exact ``spec``-view sentence the model was trained on.

        Delegates to ``orion.pack_sft.spec_prompt`` — the training-set builder —
        rather than formatting here. If that grammar ever changes, this follows
        it automatically instead of drifting silently.
        """
        problems = self.validate()
        if problems:
            raise SpecError("; ".join(problems))

        from orion.pack_sft import spec_prompt

        plan: dict[str, str] = {}
        if self.function:
            plan["function"] = self.function
        if self.manufacturing:
            plan["manufacturing"] = self.manufacturing

        return spec_prompt({"blueprint": {
            "part_class": self.part_class,
            "variables": dict(self.variables),
            "design_plan": plan,
        }})

    # ------------------------------------------------------------------ #
    def grounding(self) -> dict:
        """Everything the model is NOT told, for the UI and the conversation role.

        This is the half of the specification that makes the design defensible
        to an engineer. It is deliberately a separate method from
        :meth:`to_prompt` so that the two can never be accidentally concatenated.
        """
        return {
            "citations": list(self.citations),
            "calculations": dict(self.calculations),
            "constraints": list(self.constraints),
            "rationale": dict(self.rationale),
            "material": self.material,
            "process": self.process,
        }

    def to_dict(self) -> dict:
        return {"part_class": self.part_class,
                "variables": dict(self.variables),
                "function": self.function,
                "manufacturing": self.manufacturing,
                **self.grounding()}

    @classmethod
    def from_dict(cls, data: dict) -> "EngineeringSpecification":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


#: Words users reach for that are not the family's own name. Deliberately short:
#: a wrong family is a wrong part, and an unmatched one is a question we can ask.
_FAMILY_ALIASES = {
    "mounting plate": "mount_plate", "motor mount": "mount_plate",
    "base plate": "mount_plate", "plate": "mount_plate",
    "angle bracket": "l_bracket", "bracket": "l_bracket",
    "gusset": "gusset_plate", "rib bracket": "aero_rib_bracket",
    "flange": "bolted_flange", "housing": "gearbox_housing",
    "enclosure": "vented_enclosure", "box": "box_shell",
    "shaft": "stepped_shaft", "pulley": "v_pulley",
    "hub": "wheel_hub", "bearing housing": "bearing_carrier",
    "pillow block": "pillow_block", "manifold": "manifold_runner",
    "heat sink": "finned_rail", "heatsink": "finned_rail",
    "impeller": "impeller", "knuckle": "suspension_knuckle",
    "clevis": "clevis_mount", "lever": "bent_lever", "link": "rocker_link",
}


def choose_family(part: str) -> tuple[Optional[str], list[str]]:
    """``(family, alternatives)`` for a user's word for the part.

    Deterministic on purpose. Family choice decides which variable schema
    applies, so a model guessing here would silently change what every
    subsequent number means. When it cannot decide it returns the candidates so
    a caller can ask, rather than picking the first plausible one.
    """
    from orion.family_schema import load

    if not part:
        return None, []
    text = " ".join(str(part).lower().replace("_", " ").split())
    families = load()

    exact = text.replace(" ", "_")
    if exact in families:
        return exact, []
    if text in _FAMILY_ALIASES:
        return _FAMILY_ALIASES[text], []

    # substring, both directions: "nema 17 mount plate" contains "mount plate",
    # and "hub" is contained by "wheel hub".
    hits = [f for f in families if f.replace("_", " ") in text]
    if not hits:
        hits = [f for f in families if text in f.replace("_", " ")]
    if not hits:
        hits = sorted({fam for word, fam in _FAMILY_ALIASES.items()
                       if word in text})
    if len(hits) == 1:
        return hits[0], []
    # Prefer the most specific match when one name contains another
    # ("mount plate" over "plate").
    if hits:
        longest = max(len(h) for h in hits)
        best = [h for h in hits if len(h) == longest]
        if len(best) == 1:
            return best[0], sorted(hits)
    return None, sorted(hits)


def specification_from_intent(intent, part_hint: str = ""
                              ) -> tuple[Optional["EngineeringSpecification"],
                                         list[str]]:
    """``(specification, open_questions)`` from a parsed engineering intent.

    ``intent`` is an ``orion_agent.harness.spec.EngineeringSpec`` — what the
    user actually said, grounding-guarded so stated numbers are verbatim. This
    turns that into the form the Blueprint model expects, and it does so without
    a model of its own:

    * the family is chosen by name;
    * stated dimensions are mapped onto that family's canonical variables,
      halving any diameter that lands in a radius;
    * whatever the user did not state is filled from the corpus median, which is
      by construction a value that has verified before.

    The medians are the important part. They mean the planner in front of this
    does not have to invent a whole part to get a buildable one — it only has to
    *improve* on values that already work, and justify the ones it changes.
    Every assumed value is recorded in ``rationale`` so nothing silently
    pretends to be a requirement.
    """
    from orion.family_schema import (
        extract_for_family,
        for_family,
        resolve_dimensions,
    )

    questions: list[str] = []
    family, alternatives = choose_family(part_hint or getattr(intent, "part", ""))
    if family is None:
        questions.append(
            "could not tell which part family this is"
            + (f" — did you mean {' or '.join(alternatives)}?"
               if alternatives else ""))
        return None, questions

    schema = for_family(family)

    # Directed extraction first, from the raw sentence. A general parser reads
    # "barrel radius 29, bc radius 48, bore radius 7" as three things called
    # *radius* and keeps one; searching for each of this family's variables by
    # its own full phrase cannot lose the qualifier that distinguishes them.
    canonical = extract_for_family(part_hint, family) if part_hint else {}

    # Whatever that missed, take from the generic intent parser — it also
    # catches phrasings the schema has no word for.
    stated = dict(getattr(intent, "dimensions", None) or {})
    from_intent, unresolved = resolve_dimensions(family, stated)

    # Counts are merged separately and only into variables that ARE counts.
    # Folding them in with the dimensions let "four M5 clearance holes" resolve
    # through the "hole" synonym into hole *radius*, so a plate asked for with
    # four holes got a 4 mm hole radius — a stated-looking number that the user
    # never gave and that no guard would question.
    counts = {k: float(v) for k, v
              in (getattr(intent, "counts", None) or {}).items()}
    if counts:
        resolved_counts, count_leftovers = resolve_dimensions(family, counts)
        for name, value in resolved_counts.items():
            if "count" in (schema.variables[name].role or ""):
                from_intent.setdefault(name, value)
        unresolved.update(count_leftovers)
    claimed = {round(v, 6) for v in canonical.values()}
    for name, value in from_intent.items():
        # The fallback re-reads text the directed pass already consumed, but
        # with the qualifier stripped: "hub radius 22" comes back as
        # ``{"radius": 22}``, and a bare "radius" resolves to whichever variable
        # owns that role — putting 22 into an ``end_r`` whose true value is 3.5.
        # Its labels are unreliable by construction, so a value already claimed
        # verbatim is a duplicate reading, not a second dimension.
        if round(float(value), 6) in claimed:
            continue
        canonical.setdefault(name, value)

    rationale = {name: "stated by the user" for name in canonical}
    for name in schema.required():
        if name not in canonical:
            canonical[name] = schema.variables[name].median
            rationale[name] = (
                f"not stated — corpus median for {family} "
                f"({schema.variables[name].describe()})")

    # Numbers in the request that reached no variable. Defaulting is fine when
    # the user said nothing; it is NOT fine when they gave dimensions and the
    # extractor could not read them, because every guard still holds, every
    # variable is in range, and the specification looks perfect while
    # describing a different part. Measured on the frozen bench, five of eight
    # asks extracted nothing at all and silently became medians — a part that
    # builds, verifies, and is not what was asked for, produced by the layer
    # meant to prevent exactly that.
    import re as _re

    seen = {float(m) for m in _re.findall(r"-?\d+(?:\.\d+)?", part_hint or "")}
    used = {round(float(v), 6) for v in canonical.values()}
    orphans = sorted(v for v in seen if round(v, 6) not in used and abs(v) > 1.0)
    if orphans and part_hint:
        questions.append(
            "these numbers were given but reached no "
            f"{family} variable: {', '.join(f'{v:g}' for v in orphans)} — "
            f"the values used are defaults, so this may not be the part that "
            f"was asked for")

    for phrase, value in unresolved.items():
        questions.append(
            f"{phrase!r} = {value:g} does not map to any {family} variable "
            f"({', '.join(sorted(schema.variables))})")

    # Defaults alone always satisfy the family's guards — they come from
    # verified parts. Mixing them with values the user pinned does not: measured
    # over 200 asks, the defaults hold 100% on their own and 84.5% once a user's
    # dimensions are dropped in. Closing that gap is a search over a few scalars
    # with closed-form constraints, so it is done here, exactly, rather than
    # asked of a model that measurably did nothing else.
    from orion.constraint_repair import repair

    stated_names = set(canonical) - {
        n for n in canonical if rationale.get(n, "").startswith("not stated")}
    fix = repair(family, canonical, pinned=stated_names)
    canonical = fix["variables"]
    for change in fix["changes"]:
        rationale[change["variable"]] = (
            f"moved from {change['from']:g} to satisfy {change['guard']} "
            f"(the stated dimensions made it {change['why'].split('it was ')[-1]})"
            if "it was " in change["why"] else
            f"moved to satisfy {change['guard']}")
        if change["outside_observed_range"]:
            questions.append(
                f"{change['variable']} had to leave the range seen in verified "
                f"{family} parts to satisfy {change['guard']}")
    if not fix["ok"]:
        questions.append(fix["why"])

    spec = EngineeringSpecification(
        part_class=family,
        variables=canonical,
        material=getattr(intent, "material", "") or "",
        process=getattr(intent, "manufacturing", "") or "",
        rationale=rationale,
        constraints=list(getattr(intent, "constraints", None) or []),
    )
    questions.extend(getattr(intent, "unresolved", None) or [])
    return spec, questions


def known_vocabulary() -> dict[str, list[str]]:
    """The families and attachments the model has actually seen.

    A planner that invents ``quadcopter_frame`` puts the model off-distribution
    in a way nothing downstream will attribute correctly. This does not gate
    anything — composition legitimately produces class names no one enumerated —
    but it lets a caller warn instead of guess.
    """
    from orion.bases import BASES
    from orion.compose import ATTACHMENTS

    return {"bases": sorted(BASES), "attachments": sorted(ATTACHMENTS)}


def looks_unfamiliar(part_class: str) -> Optional[str]:
    """A warning string if ``part_class`` names no known base family, else None."""
    vocab = known_vocabulary()
    base = part_class.split("_plus_")[0]
    if base in vocab["bases"]:
        return None
    return (f"{base!r} is not one of the {len(vocab['bases'])} base families "
            f"the model was trained on; the Blueprint may still build, but the "
            f"verified-rate evidence does not cover it")
