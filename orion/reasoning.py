"""The chain from a sentence to a verified part, with every stage on the record.

An engineer asked to support a rotating shaft does not begin by choosing a
bearing. They work out what the thing must *do*, what that obliges, what the
numbers say, and only then reach for a part number — and if you ask them why the
housing bore is 51.970..52.000 they can name the standard. The answer and the
reasoning are produced together, because the reasoning is what makes the answer
checkable.

A model asked the same question emits a plausible bore. It may even be right.
But there is nothing to check, and nothing to correct when it is wrong, because
no stage of it exists as a fact — the number and its justification were sampled
at the same time from the same distribution.

So the chain is a data structure, not a prompt:

    intent -> functions -> requirements -> knowledge -> calculators
           -> selection -> specification -> blueprint -> compile -> verify

The first seven stages are deterministic. They read catalogues, apply standards
and run arithmetic, and given the same request they produce the same
specification. The model enters at ``blueprint``, and by then the numbers are
already decided — its job is to express a resolved specification as geometry,
which is the job it was fine-tuned for and the one it is reliable at.

Two properties are worth more than the tidiness:

**A stage cannot be skipped.** There is no path to a specification that did not
select a component, none to a selection that did not state a duty. A number with
no stage behind it cannot appear in the output, because there is nowhere to put
it.

**A blocked chain names its question.** Stopping at "which of radial or axial
load, and how far out of line?" is a better answer than a bearing chosen by
assuming both are zero. The questions are the ones the next stage genuinely
cannot proceed without, so they are worth asking rather than a form to fill in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from orion.knowledge import functions as F

INTENT = "intent"
FUNCTIONS = "functions"
REQUIREMENTS = "requirements"
KNOWLEDGE = "knowledge"
CALCULATORS = "calculators"
SELECTION = "selection"
SPECIFICATION = "specification"

#: The stages this module runs. Blueprint, compile and verify follow, and are
#: deliberately outside: they are the existing pipeline, and the point of the
#: chain is to hand them a specification rather than a sentence.
STAGES = (INTENT, FUNCTIONS, REQUIREMENTS, KNOWLEDGE, CALCULATORS, SELECTION,
          SPECIFICATION)


@dataclass
class Step:
    """One stage's conclusion, and what it rests on."""

    stage: str
    finding: str                                  # one line, for a human
    detail: dict[str, Any] = field(default_factory=dict)
    basis: str = ""                               # the rule, standard or sum
    #: What this stage could not decide. A non-empty list stops the chain, and
    #: is the thing to put to the user.
    asks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"stage": self.stage, "finding": self.finding}
        if self.detail:
            out["detail"] = self.detail
        if self.basis:
            out["basis"] = self.basis
        if self.asks:
            out["asks"] = self.asks
        return out


@dataclass
class Chain:
    """A reasoning trace: what was concluded at each stage, and where it ended."""

    request: str
    steps: list[Step] = field(default_factory=list)
    #: Set only when the chain reached a buildable specification.
    part_class: str = ""
    variables: dict[str, float] = field(default_factory=dict)
    rationale: dict[str, str] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.part_class and self.variables)

    @property
    def stopped_at(self) -> str:
        return self.steps[-1].stage if self.steps else ""

    def asks(self) -> list[str]:
        """The questions that must be answered for the chain to continue."""
        return list(self.steps[-1].asks) if self.steps else []

    def step(self, stage: str) -> Optional[Step]:
        for s in self.steps:
            if s.stage == stage:
                return s
        return None

    def to_dict(self) -> dict:
        return {"request": self.request,
                "steps": [s.to_dict() for s in self.steps],
                "complete": self.complete,
                "stopped_at": self.stopped_at,
                "part_class": self.part_class, "variables": self.variables,
                "rationale": self.rationale, "citations": self.citations,
                "warnings": self.warnings}

    def explain(self) -> str:
        """The trace, top to bottom. What a reviewer reads instead of guessing."""
        lines = [f"REQUEST: {self.request}", ""]
        for s in self.steps:
            lines.append(f"{s.stage.upper()}")
            lines.append(f"  {s.finding}")
            if s.basis:
                lines.append(f"  basis: {s.basis}")
            for q in s.asks:
                lines.append(f"  ASKS: {q}")
            lines.append("")
        if self.complete:
            lines.append(f"SPECIFICATION ({self.part_class})")
            for k, v in sorted(self.variables.items()):
                lines.append(f"  {k} = {v:g}   {self.rationale.get(k, '')}"
                             .rstrip())
            if self.citations:
                lines.append("  per: " + "; ".join(self.citations))
        else:
            lines.append(f"INCOMPLETE — stopped at {self.stopped_at}")
        for w in self.warnings:
            lines.append(f"NOTE: {w}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 1. intent
# --------------------------------------------------------------------------- #
#: Phrases that name a function. Small on purpose: a table that guesses is worse
#: than one that admits it does not know, because a misread function sends every
#: later stage confidently in the wrong direction.
_PHRASES: tuple[tuple[str, str], ...] = (
    (r"rotat\w*\s+shaft|shaft\s+(?:that\s+)?(?:must\s+)?(?:rotate|turn|spin)"
     r"|support\w*\s+a?\s*(?:rotating|turning|spinning)"
     r"|journal|spindle|bearing", F.SUPPORTS_ROTATION),
    (r"seal\w*|o-?ring|gland|leak|watertight|airtight", F.SEALS_FLUID),
    (r"transmit\w*\s+torque|torque\s+(?:from|to|through)|key\w*|spline"
     r"|coupl\w*", F.TRANSMITS_TORQUE),
    (r"locat\w*\s+(?:a\s+)?part|dowel|repeatable\s+position|register",
     F.LOCATES_PART),
    (r"clamp\w*|bolt\w*\s+(?:down|together)|preload|fasten",
     F.PROVIDES_CLAMP_FORCE),
    (r"retain\w*\s+axially|circlip|snap\s+ring|axial\s+retention",
     F.RETAINS_AXIALLY),
    (r"slid\w*|linear\s+(?:motion|bearing|rail)|travers\w*",
     F.SUPPORTS_LINEAR_MOTION),
    (r"gear\w*|belt|pulley|chain\s+drive|reduc\w*\s+ratio", F.TRANSFERS_POWER),
    (r"conc?entric|share\s+an?\s+axis|centr\w*|align\s+two", F.CENTERS_COMPONENT),
    (r"guid\w*\s+(?:the\s+)?motion|follow\s+a\s+path|cam\s+track",
     F.GUIDES_MOTION),
)

_UNITS = {"n": 1.0, "kn": 1000.0, "lbf": 4.4482216, "kgf": 9.80665}


def _forces(text: str) -> list[tuple[float, int, int]]:
    """Every force in the text as newtons, with where it was written.

    The position matters: "3 kN radial and 2 kN axial" is two duties, and which
    is which is decided by the word next to the number rather than by order.
    """
    out = []
    for m in re.finditer(r"(\d[\d\s,]*\.?\d*)\s*(kN|N|lbf|kgf)\b", text,
                         re.IGNORECASE):
        try:
            value = float(m.group(1).replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        out.append((value * _UNITS[m.group(2).lower()], m.start(), m.end()))
    return out


def _number(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "").replace(" ", ""))
    except (ValueError, IndexError):
        return None


_RADIAL = re.compile(r"radial|transverse|side\s*load|perpendicular", re.I)
_AXIAL = re.compile(r"axial|thrust|end\s*load|along\s+the\s+(?:axis|shaft)", re.I)


def _directed_forces(text: str) -> list[tuple[float, str, str]]:
    """Sort the forces in a request into radial and axial.

    A qualifier belongs to the number it is *nearest*, not to every number that
    can see it. "carrying 3 kN with 2 kN thrust" has one word and two figures,
    and a window wide enough to catch it from the second catches it from the
    first as well — which reads the radial load as thrust and loses it entirely.
    Claiming each word for its closest figure is what keeps the two apart.
    """
    forces = _forces(text)
    if not forces:
        return []
    words = [(m.start(), "axial_load_N") for m in _AXIAL.finditer(text)]
    words += [(m.start(), "radial_load_N") for m in _RADIAL.finditer(text)]

    claimed: dict[int, set[str]] = {i: set() for i in range(len(forces))}
    for position, kind in words:
        nearest = min(range(len(forces)),
                      key=lambda i: min(abs(position - forces[i][1]),
                                        abs(position - forces[i][2])))
        claimed[nearest].add(kind)

    out: list[tuple[float, str, str]] = []
    for i, (value, _, _) in enumerate(forces):
        kinds = claimed[i]
        if len(kinds) == 1:
            out.append((value, kinds.pop(), ""))
        elif not any(k == "radial_load_N" for k, *_ in
                     [(o[1],) for o in out]):
            # Unqualified, and no radial load read yet: a load on a shaft is
            # radial unless it says otherwise, but say so rather than assume it
            # silently.
            out.append((value, "radial_load_N",
                        f"{value:g} N read as radial — the request does not "
                        f"say which direction it acts in"))
        else:
            out.append((value, "axial_load_N",
                        f"{value:g} N read as axial — the request states two "
                        f"loads and qualifies neither"))
    return out


def read_intent(request: str) -> Step:
    """Pull the duty out of a sentence, and say what could not be read.

    Extraction proposes; the later stages dispose. Nothing here is invented: a
    figure absent from the request stays absent, because a default load is a
    number the user never gave and will never think to check.
    """
    text = " " + request.strip() + " "
    found: dict[str, Any] = {}
    notes: list[str] = []

    for value, kind, why in _directed_forces(text):
        found[kind] = value
        if why:
            notes.append(why)

    speed = _number(text, r"(\d[\d\s,]*\.?\d*)\s*(?:rpm|r/min|rev/min)")
    if speed is None:
        hz = _number(text, r"(\d[\d\s,]*\.?\d*)\s*Hz\b")
        if hz is not None:
            speed = hz * 60.0
    if speed is not None:
        found["speed_rpm"] = speed

    life = _number(text, r"(\d[\d\s,]*\.?\d*)\s*(?:hours|hrs?|h)\b")
    if life is not None:
        found["life_hours"] = life
    else:
        years = _number(text, r"(\d[\d\s,]*\.?\d*)\s*years?\b")
        if years is not None:
            found["life_hours"] = years * 8760.0
            notes.append(f"{years:g} years read as {years * 8760:g} hours of "
                         f"continuous running — derate if the duty cycle is "
                         f"intermittent")

    bore = _number(text, r"(\d[\d\s,]*\.?\d*)\s*mm\s*(?:dia\w*\s*)?"
                         r"(?:shaft|bore|journal|spindle)")
    if bore is None:
        bore = _number(text, r"(?:shaft|bore|journal|spindle)\D{0,12}?"
                             r"(\d[\d\s,]*\.?\d*)\s*mm")
    if bore is not None:
        found["bore_mm"] = bore

    mis = _number(text, r"(\d*\.?\d+)\s*(?:deg\w*|°)")
    if mis is not None:
        found["misalignment_deg"] = mis

    envelope = _number(text, r"(?:within|under|max\w*|no\s+(?:more|bigger|larger)"
                             r"\s+than)\D{0,20}?(\d[\d\s,]*\.?\d*)\s*mm\s*"
                             r"(?:outside|od|diameter|envelope|housing)")
    if envelope is not None:
        found["max_outside_dia_mm"] = envelope

    matched = []
    for pattern, function in _PHRASES:
        if re.search(pattern, text, re.IGNORECASE):
            matched.append(function)

    detail = {"duty": found, "functions": matched}
    if not matched:
        return Step(INTENT, "the request does not name a function this system "
                            "knows", detail,
                    basis="phrase table over the ten engineering functions",
                    asks=["What must the part do? " + "; ".join(
                        f"{k} ({v})" for k, v in list(F.INTENT.items())[:4])
                        + "; ..."])

    read = ", ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
                     for k, v in found.items()) or "no numbers stated"
    return Step(INTENT, f"read {read}", detail,
                basis="units in the request; nothing defaulted",
                asks=[])


# --------------------------------------------------------------------------- #
# 2-3. functions and requirements
# --------------------------------------------------------------------------- #
#: What each function cannot be decided without. Not a schema for a form — these
#: are the figures a later stage genuinely divides by.
_NEEDED: dict[str, tuple[tuple[str, str], ...]] = {
    F.SUPPORTS_ROTATION: (
        ("radial_load_N", "What radial load does the shaft carry? "
                          "The bearing is sized from it."),
        ("speed_rpm", "How fast does it turn? Life is in revolutions, so hours "
                      "cannot be computed without it."),
    ),
    F.SEALS_FLUID: (
        ("cord_dia_mm", "What cord diameter, or what bore is being sealed?"),
    ),
}

#: Figures that change the answer but have a defensible standing assumption.
#: Assumed loudly, never silently — each appears in the chain's warnings.
_ASSUMED: dict[str, tuple[tuple[str, float, str], ...]] = {
    F.SUPPORTS_ROTATION: (
        ("life_hours", 10000.0,
         "10 000 h assumed — ISO 281 rating life for general machinery; state "
         "the required life if this duty is continuous"),
        ("axial_load_N", 0.0,
         "no thrust assumed; if the shaft is loaded along its axis the bearing "
         "type may be wrong"),
        ("misalignment_deg", 0.0,
         "shaft assumed true; a deflecting shaft needs a self-aligning type"),
    ),
}


def name_functions(intent: Step) -> Step:
    functions = intent.detail.get("functions") or []
    lines = [f"{fn} — {F.INTENT[fn]}" for fn in functions if fn in F.INTENT]
    primary = functions[0]
    return Step(FUNCTIONS,
                f"{primary}" + (f" (also: {', '.join(functions[1:])})"
                                if len(functions) > 1 else ""),
                {"primary": primary, "all": functions, "reads": lines},
                basis="the function vocabulary, not a part category — the "
                      "request is answered by what it must do")


def state_requirements(intent: Step, functions: Step) -> Step:
    """Turn the read numbers into a duty, and say what is still missing.

    The distinction that matters is between a figure with a defensible standing
    assumption and one without. Rating life has one: ISO 281 names 10 000 hours
    for general machinery, and assuming it produces an answer an engineer can
    argue with. A radial load has none — assuming zero produces the smallest
    bearing in the catalogue, and it will be wrong in a way nothing downstream
    catches.
    """
    primary = functions.detail["primary"]
    duty_kwargs = dict(intent.detail.get("duty") or {})

    missing = [question for field_, question in _NEEDED.get(primary, ())
               if duty_kwargs.get(field_) is None]
    if missing:
        return Step(REQUIREMENTS,
                    f"{primary} cannot be sized from what was stated",
                    {"have": duty_kwargs}, asks=missing,
                    basis="these are divided by, not decorative")

    assumptions = []
    for field_, value, why in _ASSUMED.get(primary, ()):
        if duty_kwargs.get(field_) is None:
            duty_kwargs[field_] = value
            assumptions.append(why)

    duty = F.Duty(function=primary, **{
        k: v for k, v in duty_kwargs.items()
        if k in F.Duty.__dataclass_fields__ and k != "function"})
    stated = ", ".join(f"{k}={v:g}" for k, v in sorted(duty_kwargs.items())
                       if isinstance(v, (int, float)))
    return Step(REQUIREMENTS, f"duty: {stated}",
                {"duty": duty_kwargs, "assumptions": assumptions,
                 "_duty": duty},
                basis="stated figures, plus standing assumptions named above")


# --------------------------------------------------------------------------- #
# 4-5. knowledge and calculators
# --------------------------------------------------------------------------- #
def retrieve_knowledge(requirements: Step) -> Step:
    """Which ingested data is in scope, and where it came from.

    Named before it is used rather than after. A selection that cites its source
    only in hindsight cannot be audited for what it *failed* to consider.
    """
    from orion.knowledge.registry import dataset_for_family, families

    duty: F.Duty = requirements.detail["_duty"]
    candidates = F.families_for(duty.function)
    sources, counts = [], {}
    for family in candidates:
        from orion.knowledge.registry import rows_for_family
        counts[family] = len(rows_for_family(family))
        data = dataset_for_family(family) or {}
        src = data.get("source") or {}
        if src.get("title"):
            label = f"{src['title']}"
            if src.get("edition"):
                label += f" ({src['edition']})"
            if label not in sources:
                sources.append(label)
    if not candidates:
        known = ", ".join(families()) or "nothing"
        return Step(KNOWLEDGE, f"no ingested family performs {duty.function}",
                    {"ingested": families()},
                    asks=[f"Nothing in the catalogue performs "
                          f"{duty.function}. Ingested families: {known}."])
    total = sum(counts.values())
    return Step(KNOWLEDGE,
                f"{total} rows across {len(candidates)} "
                f"famil{'y' if len(candidates) == 1 else 'ies'}",
                {"families": counts, "sources": sources},
                basis="; ".join(sources) or "ingested datasets")


def name_calculators(requirements: Step) -> Step:
    """The arithmetic that will decide this, declared before it runs."""
    duty: F.Duty = requirements.detail["_duty"]
    used = {
        F.SUPPORTS_ROTATION: [
            ("bearing_life_l10", "ISO 281 basic rating life: "
                                 "L10h = (C/P)^p x 10^6 / (60n)"),
            ("type profile", "which bearing types take this combination of "
                             "radial load, thrust and misalignment at all"),
            ("ISO 286 seat fits", "the shaft and housing tolerance classes for "
                                  "the load case"),
        ],
    }.get(duty.function, [])
    if not used:
        return Step(CALCULATORS, "no calculator registered for "
                                 f"{duty.function}; selection is by envelope "
                                 f"and stated limits only", {})
    return Step(CALCULATORS, "; ".join(name for name, _ in used),
                {"calculators": [{"name": n, "does": d} for n, d in used]},
                basis="deterministic — the model does not compute these")


# --------------------------------------------------------------------------- #
# 6-7. selection and specification
# --------------------------------------------------------------------------- #
def select_component(requirements: Step) -> Step:
    """The part, chosen by the duty rather than proposed and then justified."""
    duty: F.Duty = requirements.detail["_duty"]
    found = F.search(duty, limit=5)
    if not found:
        why = F.explain_empty(duty)
        # The question, not the whole explanation. The reasoning belongs in
        # `basis`, where `explain()` prints it intact rather than flattened into
        # an unreadable line.
        ask = next((line.strip() for line in why.splitlines()
                    if line.startswith("closest")),
                   "Relax one of the stated requirements, or widen the "
                   "catalogue.")
        return Step(SELECTION, "nothing in the catalogue satisfies this duty",
                    {"duty": duty.__dict__}, basis=why,
                    asks=[f"No catalogued part takes this duty — {ask}"])
    best = found[0]
    alternatives = [{"designation": c.designation, "family": c.family,
                     "evidence": c.evidence} for c in found[1:]]

    # What choosing this type costs the rest of the design. A taper roller sized
    # purely on life is a correct bearing and an incomplete decision: it takes
    # thrust one way and must be mounted against an opposed partner, which is a
    # second bearing and a preload nobody asked for.
    notes: list[str] = []
    from orion.knowledge.bearing_types import classify, profile
    from orion.knowledge.registry import rows_for_family

    spec = profile(classify(best.designation) or "")
    if spec is not None and spec.caution:
        notes.append(f"{best.designation} is a {spec.kind}: {spec.caution}")
    if duty.bore_mm is None and best.evidence.get("bearing_type"):
        rows = {r.get("designation"): r for r in rows_for_family(best.family)}
        bore = (rows.get(best.designation) or {}).get("d")
        if bore is not None:
            notes.append(f"shaft diameter was not stated, so it is an output "
                         f"rather than a constraint: this selection sets it to "
                         f"{bore:g} mm")

    return Step(SELECTION, f"{best.designation} ({best.family})",
                {"chosen": best.to_dict(), "alternatives": alternatives,
                 "notes": notes, "_candidate": best},
                basis="; ".join(f"{k}={v}" for k, v in best.evidence.items()
                                if k != "basis"))


def write_specification(selection: Step) -> Step:
    """Resolve the selected component into buildable variables.

    This is the handoff. Everything above decided *what*; the skill turns it
    into dimensions with the standard beside each one, and that is what the
    model is given — a resolved specification rather than a sentence to
    interpret.
    """
    from orion.skills.base import SkillError, registry

    candidate: F.Candidate = selection.detail["_candidate"]
    skills = registry.for_function(candidate.function)
    if not skills:
        return Step(SPECIFICATION,
                    f"no skill builds geometry for {candidate.function}",
                    {"selected": candidate.designation},
                    asks=[f"{candidate.designation} satisfies the duty, but no "
                          f"skill turns {candidate.function} into geometry yet."])
    skill = skills[0]
    try:
        result = skill.run(candidate.designation)
    except SkillError as exc:
        return Step(SPECIFICATION, f"{skill.name} refused: {exc}",
                    {"selected": candidate.designation},
                    asks=[str(exc)])
    return Step(SPECIFICATION, f"{result.part_class} from {skill.name}",
                {"part_class": result.part_class,
                 "variables": result.variables,
                 "derived": result.derived, "_result": result},
                basis="; ".join(result.citations))


# --------------------------------------------------------------------------- #
def reason(request: str) -> Chain:
    """Run the chain as far as the request allows.

    Stops at the first stage that cannot proceed, with its question attached.
    That is the design: a chain that runs to completion on a request missing the
    load has not been robust, it has invented one.
    """
    F.load_all()
    chain = Chain(request=request)

    def add(step: Step) -> bool:
        chain.steps.append(step)
        return not step.asks

    if not add(read_intent(request)):
        return chain
    if not add(name_functions(chain.steps[-1])):
        return chain
    if not add(state_requirements(chain.steps[0], chain.steps[1])):
        return chain
    requirements = chain.steps[-1]
    chain.warnings.extend(requirements.detail.get("assumptions", []))

    if not add(retrieve_knowledge(requirements)):
        return chain
    if not add(name_calculators(requirements)):
        return chain
    if not add(select_component(requirements)):
        return chain
    selection = chain.steps[-1]
    chain.warnings.extend(selection.detail.get("notes", []))

    if not add(write_specification(selection)):
        return chain

    result = chain.steps[-1].detail["_result"]
    chain.part_class = result.part_class
    chain.variables = dict(result.variables)
    chain.rationale = dict(result.rationale)
    chain.citations = list(result.citations)
    chain.warnings.extend(result.warnings)
    return chain


def design_prompt(chain: Chain) -> str:
    """What the Blueprint model is given: dimensions, not a sentence.

    The register the model was fine-tuned on is a resolved parametric part, and
    this is the point of the seven stages above — by the time the model sees the
    request, every number in it has been decided by a standard or a calculation.
    Reasoning is deliberately withheld: it is what the *user* is shown, and
    feeding it back to the model invites it to re-litigate settled arithmetic.
    """
    if not chain.complete:
        raise ValueError(f"chain stopped at {chain.stopped_at}; "
                         f"nothing to build")
    dims = ", ".join(f"{k}={v:g}" for k, v in sorted(chain.variables.items()))
    return f"Build a {chain.part_class} with {dims}."
