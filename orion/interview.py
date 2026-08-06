"""Ask until the request is complete. Never invent.

The fine-tune drifts because it was taught to fill gaps. Every training prompt
ended with *"Choose sensible values for anything I have not given"*, and 91.7%
of the corpus is a base part carrying one to three extra features — so a terse
request lands out of distribution and the model does what it was rewarded for:
it adds things. Asking for *"Rectangular plate 100 x 60 x 5 mm"* returns
``rect_plate_plus`` at 29336 mm³ against a closed form of 30000, and it is
graded VERIFIED because the assertions it is checked against are its own.

This module removes the gap instead of asking a model to resist it. A request
is decomposed into named slots; the slots a part *cannot* be built without are
declared per family; anything still missing becomes a question rather than a
guess. Only when the required set is complete does anything get emitted.

Three deliberate choices:

**Required is per family, not global.** A rectangular plate needs length, width
and thickness — a corner radius is a refinement and asking for it is noise. A
bearing housing without a bore diameter is not a housing. One "is anything
missing" rule produces an interrogation for a plate and a guess for a housing.

**Extraction is a model job; validation is not.** The model reads
``"120 × 80 × 10"`` and ``"M8 clearance"`` and reports slots. Whether the set is
complete is then decided by :func:`missing`, in Python, against the schema. A
model that claims completeness it does not have cannot talk its way past this.

**The model never converts units, halves a diameter, or applies a standard.**
``M8 clearance`` becomes 9.0 mm from :data:`CLEARANCE`, not from the model's
memory of ISO 273. Diameters become radii in :func:`resolve`. This is the same
rule the rest of the codebase runs on: the model decides *which* value applies,
Python decides *what it is*.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# standards — looked up, never recalled
# --------------------------------------------------------------------------- #
#: ISO 273 medium-series clearance holes, in mm. A model asked for "M8
#: clearance" must not answer from memory; it names the thread and this decides.
CLEARANCE = {"M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 9.0,
             "M10": 11.0, "M12": 13.5, "M16": 17.5, "M20": 22.0}

#: ISO 7046 / DIN 74 counterbore diameters for socket head screws, mm.
COUNTERBORE = {"M3": 6.5, "M4": 8.0, "M5": 10.0, "M6": 11.0, "M8": 15.0,
               "M10": 18.0, "M12": 20.0}

#: ISO 228 (G) parallel pipe thread tapping drills, mm.
TAPPING = {"G1/8": 8.8, "G1/4": 11.8, "G3/8": 15.25, "G1/2": 19.0,
           "G3/4": 24.5, "G1": 30.75}


# --------------------------------------------------------------------------- #
# what each family cannot be built without
# --------------------------------------------------------------------------- #
#: The schema, loaded from data rather than declared in code.
#:
#: ``part_families.yaml`` is versioned and is the single source of truth for
#: what a family needs. The extraction prompt is generated FROM it, so a family
#: added there is asked about correctly without touching a prompt — and the two
#: cannot drift apart, which they would the moment a field existed in one and
#: not the other.
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "part_families.yaml")


@dataclass(frozen=True)
class Slot:
    name: str
    prompt: str
    unit: str = "mm"
    #: A diameter the request states but the Blueprint stores as a radius.
    #: Halved in :func:`resolve`, never by the model.
    diameter: bool = False
    #: A value that must stay a string — a material, a thread designation.
    text: bool = False
    #: Fields that become required once this one is given.
    #:
    #: A slot length is optional — plenty of plates have no slots — but a plate
    #: that *has* slots and no stated distance from the edge is under-specified,
    #: and "near each corner" does not fix a position. Without this the gap
    #: surfaced as a generator refusal after the interview had already declared
    #: itself complete, which is the wrong end of the pipeline to discover a
    #: question at.
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class Family:
    name: str
    label: str
    required: tuple[Slot, ...]
    optional: tuple[Slot, ...] = ()

    def slot(self, name: str) -> Optional[Slot]:
        for s in self.required + self.optional:
            if s.name == name:
                return s
        return None


def _slots_of(block: dict) -> tuple[Slot, ...]:
    out = []
    for name, spec in (block or {}).items():
        spec = spec or {}
        out.append(Slot(
            name=name,
            prompt=spec.get("ask") or f"What is the {name.replace('_', ' ')}?",
            unit=spec.get("unit", "mm"),
            diameter=bool(spec.get("diameter")),
            text=bool(spec.get("text")),
            requires=tuple(spec.get("requires") or ()),
        ))
    return tuple(out)


def load_schema(path: str = SCHEMA_PATH) -> tuple[int, dict[str, Family]]:
    """(version, families). Raises rather than falling back to a default.

    A missing or malformed schema must not degrade to "no required fields",
    because that failure is invisible: the interview would simply stop asking
    and every part would be built from whatever the request happened to state.
    """
    import yaml

    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    fams = doc.get("families") or {}
    if not fams:
        raise ValueError(f"no families defined in {path}")
    out: dict[str, Family] = {}
    for name, spec in fams.items():
        spec = spec or {}
        required = _slots_of(spec.get("required"))
        if not required:
            raise ValueError(f"family {name!r} declares no required fields")
        out[name] = Family(name=name,
                           label=spec.get("label") or name.replace("_", " "),
                           required=required,
                           optional=_slots_of(spec.get("optional")))
    return int(doc.get("version", 0)), out


SCHEMA_VERSION, FAMILIES = load_schema()

#: Offered to the model so it picks from a closed set rather than inventing a
#: name nothing downstream knows how to build.
FAMILY_NAMES = tuple(FAMILIES)


# --------------------------------------------------------------------------- #
# the state of one interview
# --------------------------------------------------------------------------- #
@dataclass
class Interview:
    request: str
    family: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    answers: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.family) and not missing(self.family, self.slots)

    def to_dict(self) -> dict:
        return {"request": self.request, "family": self.family,
                "slots": dict(self.slots), "asked": list(self.asked),
                "complete": self.complete, "notes": list(self.notes)}


def missing(family: str, slots: dict) -> list[Slot]:
    """Required slots with no value. The completeness test, in Python.

    Optional slots are never returned: asking a user for a corner radius they
    did not mention is how an assistant becomes tiring, and the absence of a
    refinement is not the absence of information.
    """
    fam = FAMILIES.get(family)
    if fam is None:
        return []

    def absent(name: str) -> bool:
        return slots.get(name) is None or slots.get(name) == ""

    gaps = [s for s in fam.required if absent(s.name)]
    # Conditionally required: a field only becomes necessary once the thing it
    # qualifies has been asked for. Ordered after the unconditional ones so the
    # interview establishes the envelope before the detail.
    for s in fam.required + fam.optional:
        if absent(s.name):
            continue
        for name in s.requires:
            dep = fam.slot(name)
            if dep is not None and absent(name) and dep not in gaps:
                gaps.append(dep)
    return gaps


def question_for(slot: Slot) -> str:
    """One question, from the schema. Not generated, so it cannot drift."""
    return slot.prompt


def resolve(family: str, slots: dict) -> dict:
    """Slots as the Blueprint stores them: radii, not diameters.

    Applied here rather than asked of the model, because "40 mm bore" and "bore
    radius 20" are the same fact and a model that halves it sometimes is worse
    than one that never does.
    """
    fam = FAMILIES.get(family)
    if fam is None:
        return dict(slots)
    out: dict[str, Any] = {}
    for key, value in slots.items():
        s = fam.slot(key)
        if s is not None and s.diameter and isinstance(value, (int, float)):
            out[key.removesuffix("_d") + "_r"] = float(value) / 2.0
        else:
            out[key] = value
    return out


def apply_standards(slots: dict, family: str = "") -> tuple[dict, list[str]]:
    """Turn named threads into dimensions from the tables above.

    Returns the slots plus a note for every substitution, so a user can see
    that 9.0 mm came from ISO 273 and not from a model's recollection.

    Only fills fields the family actually declares. Naming M10 in a request
    otherwise handed a counterbore diameter to a bearing housing that has no
    counterbore, and the generator then reported a feature the user never asked
    for as unbuildable — a standards lookup inventing work.
    """
    fam = FAMILIES.get(family) if family else None

    def wanted(name: str) -> bool:
        return fam is None or fam.slot(name) is not None

    out = dict(slots)
    notes: list[str] = []
    thread = str(out.get("thread") or out.get("hole_thread") or "").upper()
    if thread in CLEARANCE and out.get("hole_d") is None and wanted("hole_d"):
        out["hole_d"] = CLEARANCE[thread]
        notes.append(f"{thread} clearance hole = {CLEARANCE[thread]} mm (ISO 273 medium)")
    if (thread in COUNTERBORE and out.get("cbore_d") is None
            and wanted("cbore_d")):
        out["cbore_d"] = COUNTERBORE[thread]
        notes.append(f"{thread} counterbore = {COUNTERBORE[thread]} mm (ISO 7046)")
    port = str(out.get("port_thread") or "").upper().replace(" ", "")
    if port in TAPPING and out.get("port_d") is None and wanted("port_d"):
        out["port_d"] = TAPPING[port]
        notes.append(f"{port} tapping drill = {TAPPING[port]} mm (ISO 228)")
    return out, notes


# --------------------------------------------------------------------------- #
# the model's two jobs
# --------------------------------------------------------------------------- #
#: ``other`` is not decoration.
#:
#: A closed list with no way out forces every request into it: a helical
#: compression spring came back as a bearing housing, and the interview then
#: asked for its overall length and width. Downstream that is worse than not
#: matching at all, because a request nothing here can build must reach the
#: path that can. Offering the escape costs one line and restores it.
IDENTIFY_SYSTEM = """You are OrionFlow's Engineering Requirements Interpreter.

Read the request and name the part family. Nothing else.

Choose "other" unless the request is clearly one of the listed families. A wrong
match is worse than no match: it sends the request down a path that cannot build
it. Springs, gears, shafts, pipes, castings and anything not listed are "other".

Reply with ONE JSON object and nothing else:
{"family": "<one of: %s, other>"}
""" % ", ".join(FAMILY_NAMES)


#: The extraction prompt is built per family and *names every slot*.
#:
#: Without the target names a capable model still reads every number correctly
#: and then reports them under a structure of its own — ``overall_dimensions:
#: {length: 300, thickness: 16}`` rather than ``length``/``thickness``. Measured
#: 0/17 on the first run purely for that reason, with zero wrong values. Asking
#: a model to guess your schema is not extraction, it is a riddle.
EXTRACT_SYSTEM = """You are OrionFlow's Engineering Requirements Interpreter.

Read the request and report ONLY the values it actually states, using EXACTLY \
the field names listed below. You do not design anything and you do not fill \
gaps.

Rules:
- Use the exact field names given. Do not nest, group or rename them.
- Report ONLY values the request states. Never invent a dimension, material, \
tolerance, load or standard.
- If a value is absent, OMIT the key entirely. Never write null, 0 or a guess.
- Report diameters exactly as stated. Do NOT halve them.
- For a thread designation (M8, G1/4), put the designation itself in `thread` \
or `port_thread`. Do NOT convert it to a drill size — that is looked up from a \
standard, not recalled.
- Numbers must be plain numbers, not strings and not expressions.

Fields for a %s:

REQUIRED (report every one the request states):
%s

OPTIONAL (report only if stated):
%s

Reply with ONE JSON object of field names to values, and nothing else."""


def extract_prompt(family: str) -> str:
    """The extraction system prompt for one family, naming its slots."""
    fam = FAMILIES[family]

    def show(slots) -> str:
        return "\n".join(
            f"  {s.name} — {s.prompt}" + (" (diameter)" if s.diameter else "")
            for s in slots
        ) or "  (none)"

    return EXTRACT_SYSTEM % (
        family.replace("_", " "), show(fam.required), show(fam.optional))


def _json_of(text: str) -> Optional[dict]:
    """First balanced JSON object in a reply. Tolerates fences and prose."""
    if not text:
        return None
    body = text
    if "</think>" in body:
        body = body.rpartition("</think>")[2]
    body = re.sub(r"```(?:json)?", "", body)
    start = body.find("{")
    if start == -1:
        return None
    depth, instr, esc = 0, False, False
    for i, ch in enumerate(body[start:], start):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            instr = not instr
            continue
        if instr:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(body[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _known_slots(family: str, raw: dict) -> dict:
    """Keep what the schema declares; drop the rest.

    A value under a name no family declares cannot reach a template, so keeping
    it would only make the interview look more complete than it is.
    """
    fam = FAMILIES[family]
    names = {s.name for s in fam.required + fam.optional} | {
        "thread", "hole_thread", "port_thread"}
    out = {}
    for k, v in raw.items():
        if k not in names or v is None or v == "":
            continue
        if isinstance(v, str) and k not in ("material", "thread", "hole_thread",
                                            "port_thread", "port_count",
                                            "hole_count", "inlet_thread"):
            try:
                v = float(v.strip().rstrip("mm").strip())
            except ValueError:
                continue
        out[k] = v
    return out


#: Completion budget per call.
#:
#: The served Qwen3-32B has ``max_model_len`` 8192 — prompt *and* completion
#: together. Asking for 8192 completion tokens is therefore never satisfiable
#: and vLLM rejects the request outright, which surfaced as an empty reply and
#: read exactly like a model that had nothing to say. Leave room for the prompt.
READ_TOKENS = 2048
EMIT_TOKENS = 4096


def read_request(client, request: str, max_tokens: int = READ_TOKENS) -> Interview:
    """Two model calls: name the family, then extract against its schema.

    Split deliberately. The slot list is family-specific and listing every
    family's fields in one prompt is both enormous and an invitation to mix
    them; naming the family first means the extraction prompt contains only the
    fields that can apply.
    """
    from orion_agent.harness.llm.base import LLMMessage

    ident = client.chat(
        [LLMMessage.system(IDENTIFY_SYSTEM), LLMMessage.user(request)],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    # A transport failure is not a classification. Adapters return it as
    # content rather than raising, so without this an unreachable endpoint
    # became "rect_plate with no dimensions" and the interview asked the user
    # how long their plate was — an outage reported as a question about their
    # request.
    if getattr(ident, "finish_reason", "") == "error" or not (ident.content or "").strip():
        return Interview(request=request)

    family = str((_json_of(ident.content) or {}).get("family") or "")
    if family not in FAMILIES:
        return Interview(request=request)

    got = client.chat(
        [LLMMessage.system(extract_prompt(family)), LLMMessage.user(request)],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    raw = _json_of(got.content) or {}
    slots = _known_slots(family, raw if isinstance(raw, dict) else {})
    slots, notes = apply_standards(slots, family)
    return Interview(request=request, family=family, slots=slots, notes=notes)


def next_question(iv: Interview) -> Optional[str]:
    """The next thing to ask, or None when the required set is complete."""
    if not iv.family:
        return ("What kind of part is this? I can build: "
                + ", ".join(n.replace("_", " ") for n in FAMILY_NAMES) + ".")
    gaps = [s for s in missing(iv.family, iv.slots) if s.name not in iv.asked]
    if not gaps:
        return None
    iv.asked.append(gaps[0].name)
    return question_for(gaps[0])


def answer(iv: Interview, slot_name: str, value: Any) -> Interview:
    """Record an answer. A later answer replaces an earlier one.

    Replacement rather than accumulation is the point: a user who corrects a
    dimension means the new one, and merging both is how an assistant produces
    a part that satisfies neither.
    """
    iv.slots[slot_name] = value
    iv.slots, notes = apply_standards(iv.slots, iv.family)
    for n in notes:
        if n not in iv.notes:
            iv.notes.append(n)
    iv.answers.append((slot_name, str(value)))
    return iv


def requirements(iv: Interview) -> dict:
    """The Requirements object: the interview's only output.

    This is the handoff, and it is deliberately not a Blueprint. Everything
    above this line is language; everything below it is arithmetic. Radii are
    already resolved, standards already applied, and the schema version is
    recorded so a requirements set can be re-read after the schema moves on.
    """
    gaps = missing(iv.family, iv.slots)
    if gaps:
        raise ValueError("interview incomplete; still missing: "
                         + ", ".join(s.name for s in gaps))
    out = {"family": iv.family, "schema_version": SCHEMA_VERSION}
    out.update(resolve(iv.family, iv.slots))
    if iv.notes:
        out["standards_applied"] = list(iv.notes)
    return out


def build(iv: Interview) -> dict:
    """Complete interview -> Blueprint. Deterministic; no model is called.

    The model used to write this, and measurement said to stop. Given a
    complete specification the base model failed the static check on every
    complex part, and the fine-tune returned
    ``l_bracket_plus_counterbore_set_vent_slot`` — adding a vent slot to a
    request that had already stated every dimension. One built out of five,
    either way.

    ``orion.blueprint_gen`` writes the feature tree instead. It cannot add a
    feature nobody asked for because there is no step at which one could be
    introduced, and its closed-form volume is derived alongside the geometry
    rather than predicted about it.
    """
    from orion import blueprint_gen

    return blueprint_gen.generate(iv.family, requirements(iv))
