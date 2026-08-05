"""Ask until the request is complete, then emit. Never invent.

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
@dataclass(frozen=True)
class Slot:
    name: str
    prompt: str
    unit: str = "mm"
    #: A diameter the Blueprint stores as a radius. Halved in :func:`resolve`,
    #: never by the model — "40 mm bore" and "bore radius 20" are the same fact
    #: and only one of them is what the template holds.
    diameter: bool = False


@dataclass(frozen=True)
class Family:
    name: str
    required: tuple[Slot, ...]
    optional: tuple[Slot, ...] = ()

    def slot(self, name: str) -> Optional[Slot]:
        for s in self.required + self.optional:
            if s.name == name:
                return s
        return None


_L = Slot("length", "How long should the part be (overall)?")
_W = Slot("width", "How wide should the part be (overall)?")
_T = Slot("thickness", "How thick should it be?")
_H = Slot("height", "How tall should it be (overall)?")

FAMILIES: dict[str, Family] = {
    "rect_plate": Family(
        "rect_plate",
        required=(_L, _W, _T),
        optional=(
            Slot("corner_radius", "Corner radius?"),
            Slot("bore_d", "Central bore diameter?", diameter=True),
            Slot("hole_count", "How many mounting holes?", unit=""),
            Slot("hole_d", "Mounting hole diameter?", diameter=True),
            Slot("pcd", "Bolt circle diameter?", diameter=True),
            Slot("pocket_l", "Pocket length?"),
            Slot("pocket_w", "Pocket width?"),
            Slot("pocket_depth", "Pocket depth?"),
            Slot("fillet", "External fillet radius?"),
            Slot("chamfer", "Edge chamfer size?"),
            Slot("material", "Material?", unit=""),
        ),
    ),
    "l_bracket": Family(
        "l_bracket",
        required=(
            Slot("base_length", "How long is the base plate?"),
            Slot("base_width", "How wide is the base plate?"),
            Slot("base_thickness", "How thick is the base plate?"),
            Slot("upright_height", "How tall is the vertical plate?"),
            Slot("upright_thickness", "How thick is the vertical plate?"),
        ),
        optional=(
            Slot("upright_width", "How wide is the vertical plate?"),
            Slot("inside_fillet", "Inside fillet radius at the joint?"),
            Slot("bore_d", "Pilot bore diameter on the vertical plate?",
                 diameter=True),
            Slot("hole_d", "Mounting hole diameter?", diameter=True),
            Slot("bolt_square", "Square bolt pattern spacing?"),
            Slot("cbore_d", "Counterbore diameter?", diameter=True),
            Slot("cbore_depth", "Counterbore depth?"),
            Slot("slot_length", "Mounting slot length?"),
            Slot("slot_width", "Mounting slot width?"),
            Slot("fillet", "External fillet radius?"),
            Slot("chamfer", "Edge chamfer size?"),
            Slot("material", "Material?", unit=""),
        ),
    ),
    "bearing_housing": Family(
        "bearing_housing",
        required=(
            _L, _W, _H,
            Slot("bore_d", "What is the bearing seat diameter?", diameter=True),
            Slot("seat_depth", "How deep is the bearing seat?"),
        ),
        optional=(
            Slot("shoulder", "Locating shoulder width?"),
            Slot("recess_d", "Flange recess diameter?", diameter=True),
            Slot("recess_depth", "Flange recess depth?"),
            Slot("hole_d", "Mounting hole diameter?", diameter=True),
            Slot("hole_pitch_x", "Hole spacing along the length?"),
            Slot("hole_pitch_y", "Hole spacing across the width?"),
            Slot("fillet", "Fillet radius where the feet meet the body?"),
            Slot("chamfer", "Edge chamfer size?"),
            Slot("material", "Material?", unit=""),
        ),
    ),
    "manifold": Family(
        "manifold",
        required=(
            _L, _W, _H,
            Slot("passage_d", "What diameter is the main passage?",
                 diameter=True),
        ),
        optional=(
            Slot("port_count", "How many ports?", unit=""),
            Slot("port_thread", "Port thread size?", unit=""),
            Slot("port_d", "Port tapping drill diameter?", diameter=True),
            Slot("inlet_thread", "Inlet thread size?", unit=""),
            Slot("hole_d", "Mounting hole diameter?", diameter=True),
            Slot("cbore_d", "Counterbore diameter?", diameter=True),
            Slot("cbore_depth", "Counterbore depth?"),
            Slot("fillet", "External fillet radius?"),
            Slot("chamfer", "Edge chamfer size?"),
            Slot("material", "Material?", unit=""),
        ),
    ),
}

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
    return [s for s in fam.required
            if slots.get(s.name) is None or slots.get(s.name) == ""]


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


def apply_standards(slots: dict) -> tuple[dict, list[str]]:
    """Turn named threads into dimensions from the tables above.

    Returns the slots plus a note for every substitution, so a user can see
    that 9.0 mm came from ISO 273 and not from a model's recollection.
    """
    out = dict(slots)
    notes: list[str] = []
    thread = str(out.get("thread") or out.get("hole_thread") or "").upper()
    if thread in CLEARANCE and out.get("hole_d") is None:
        out["hole_d"] = CLEARANCE[thread]
        notes.append(f"{thread} clearance hole = {CLEARANCE[thread]} mm (ISO 273 medium)")
    if thread in COUNTERBORE and out.get("cbore_d") is None:
        out["cbore_d"] = COUNTERBORE[thread]
        notes.append(f"{thread} counterbore = {COUNTERBORE[thread]} mm (ISO 7046)")
    port = str(out.get("port_thread") or "").upper().replace(" ", "")
    if port in TAPPING and out.get("port_d") is None:
        out["port_d"] = TAPPING[port]
        notes.append(f"{port} tapping drill = {TAPPING[port]} mm (ISO 228)")
    return out, notes


# --------------------------------------------------------------------------- #
# the model's two jobs
# --------------------------------------------------------------------------- #
IDENTIFY_SYSTEM = """You are OrionFlow's Engineering Requirements Interpreter.

Read the request and name the part family. Nothing else.

Reply with ONE JSON object and nothing else:
{"family": "<one of: %s>"}
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


#: A real, frozen, verified Blueprint. Shown rather than described.
#:
#: Describing the schema in prose produced a JSON object with no ``part_class``
#: and no features — a capable model inventing a plausible shape because it had
#: never been shown the real one. The fine-tune knows this format from 23k
#: examples; a general model has to be given it once.
EMIT_EXAMPLE = """{
  "part_class": "tee_plate",
  "variables": {"span": 128, "stem": 64, "w": 27, "t": 12.5, "end_r": 4.25},
  "datums": {"A": "bottom face z=0 (primary)", "B": "long edge (secondary)"},
  "design_plan": {"derivation": [
    {"step": 1, "eq": "A = (span*w + stem*w)", "why": "disjoint bar plus stem"},
    {"step": 2, "eq": "V = (A - 3*pi*end_r^2)*t", "why": "three bores"}]},
  "assertions": [
    {"id": "limb_width", "kind": "precondition", "tier": 1,
     "target": "w - 2*end_r - 5"},
    {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
     "tol_rel": 1e-06, "target": "span"},
    {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
     "target": "((span*w + stem*w) - 3*pi*end_r**2)*t"}],
  "template": {
    "features": [
      {"id": "Body", "type": "Body", "parameters": {}},
      {"id": "s0", "type": "Sketch", "parameters": {}},
      {"id": "tee", "type": "Pad", "rationale": "plate with bores in-profile",
       "parameters": {"Length": "t", "Type": "Length"}}],
    "sketches": [
      {"id": "s0", "plane": "XY", "profile": {"builder": "rect_with_holes",
       "args": {"w": "span", "h": "w",
                "holes": [["-span/2 + w/2", "0", "end_r"],
                          ["span/2 - w/2", "0", "end_r"]]}}}],
    "dependencies": [{"source": "s0", "target": "tee", "kind": "profile"}]}
}"""


EMIT_SYSTEM = """You are OrionFlow's Blueprint emitter.

Every dimension has already been decided and is given to you. Your only job is \
to express them in the Blueprint format below. You are not designing.

THE FORMAT — follow it exactly:
""" + EMIT_EXAMPLE + """

Rules that are not negotiable:
- Top-level keys are exactly: part_class, variables, datums, design_plan, \
assertions, template. All six are required.
- `variables` holds plain numbers. EVERYWHERE ELSE, every dimension is a STRING \
expression over those variable names — never a bare number. "Length": "t", not \
"Length": 12.5.
- Every declared variable must be referenced by some feature, sketch or \
assertion, or the Blueprint is rejected.
- Exactly one assertion of kind "body_volume" whose `target` is the exact closed \
form of the solid you emitted. Use ** for powers and `pi` for π.
- Use ONLY the dimensions provided. Do not add features nobody asked for.
- Prefer putting holes and slots IN the sketch profile (rect_with_holes, \
poly_with_holes, hole_grid, bolt_circle) rather than as separate Pockets — the \
volume is then one closed form.

Feature types: Body, Sketch, Pad, Pocket, Revolution, Groove, Hole, Fillet, \
Chamfer, Draft, Thickness, LinearPattern, PolarPattern, Mirrored, Loft, Sweep.
Profile builders: circle, annulus, rect, rect_with_holes, rounded_rect, slot, \
bolt_circle, regular_polygon, polyline, poly_with_holes, hole_grid, arc_spine.

Reply with ONE JSON object and nothing else."""


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
    slots, notes = apply_standards(slots)
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
    iv.slots, notes = apply_standards(iv.slots)
    for n in notes:
        if n not in iv.notes:
            iv.notes.append(n)
    iv.answers.append((slot_name, str(value)))
    return iv


def emit(client, iv: Interview, max_tokens: int = EMIT_TOKENS
         ) -> tuple[Optional[dict], str]:
    """Blueprint JSON from a complete interview. Refuses an incomplete one."""
    from orion_agent.harness.llm.base import LLMMessage

    gaps = missing(iv.family, iv.slots)
    if gaps:
        raise ValueError("interview incomplete; still missing: "
                         + ", ".join(s.name for s in gaps))

    # The decided dimensions and nothing else. Including the original prose
    # here made the model re-derive instead of format: 72,602 characters of
    # reasoning and the entire 16k budget spent without emitting a character,
    # on a request whose numbers were already settled. Removing it produced the
    # Blueprint in ~7.5k tokens. This is the same rule ``propose()`` follows
    # when it withholds the chain's derivation — a decision shown to a model is
    # a decision it will reopen.
    resolved = resolve(iv.family, iv.slots)
    spec = {"part_family": iv.family, "dimensions_mm": resolved}
    if iv.notes:
        spec["standards_applied"] = iv.notes
    # Compact, not pretty-printed. Measured, twice, same spec and seed:
    # ``json.dumps(spec)`` finishes in 7,532 tokens; ``indent=2`` reasons for
    # 70,297 characters and exhausts a 16k budget without emitting anything.
    # Whitespace in the input is not free with a reasoning model.
    reply = client.chat(
        [LLMMessage.system(EMIT_SYSTEM), LLMMessage.user(json.dumps(spec))],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return _json_of(reply.content), reply.content
