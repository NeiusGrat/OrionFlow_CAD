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

#: NEMA ICS 16 stepper motor frames: (face across flats, bolt square, screw).
#:
#: The knowledge layer, reaching the live path. "NEMA 17 motor mount plate,
#: 6 mm thick: M3 holes on a 31 x 31 mm square bolt pattern" states the pattern
#: and never states the plate — so the interview asked how long the plate
#: should be, about the one dimension in mechanical engineering that a
#: designation fixes exactly. An engineer would not ask; they would know the
#: face is 42.3 mm square, and say where they got it.
#:
#: The bolt square is carried too, so a request that names the frame and not the
#: pattern is still complete — and it is a 2 x 2 grid at that pitch, which is
#: what a square bolt pattern is.
MOTOR_FRAMES = {
    "NEMA 8": (20.3, 16.0, "M2"),
    "NEMA 11": (28.2, 23.0, "M2.5"),
    "NEMA 14": (35.2, 26.0, "M3"),
    "NEMA 17": (42.3, 31.0, "M3"),
    "NEMA 23": (56.4, 47.14, "M5"),
    "NEMA 34": (86.0, 69.6, "M6"),
}

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
    #: Fields of which *at least one* must be given once this one is.
    #:
    #: ``requires`` is an AND and some requirements are genuinely a choice. A
    #: mounting hole pattern needs a *placement*, and there is more than one
    #: kind: on a bolt circle, or inset from the corners. Demanding both asks
    #: for a bolt circle diameter that a corner pattern does not have; demanding
    #: neither is how "four M5 clearance holes, one 10 mm from each corner"
    #: became a plate with no holes at all — the count and the diameter were
    #: read, no placement was, and the builder had nowhere to put them.
    #:
    #: The question asked is the first named field's, since the alternatives are
    #: phrasings of one question rather than several.
    requires_any: tuple[str, ...] = ()
    #: Takes this other slot's value when the request states only one of them.
    #:
    #: An L-bracket cut from one plate has one thickness, and "60 x 40 base and
    #: a 60 x 50 vertical wall, 4 mm thick" states it once. Two separate
    #: required slots turned that into two questions the request had already
    #: answered — the assistant asking "how thick is the vertical plate?" about
    #: a sentence ending "4 mm thick". Three of the sixteen benchmark prompts
    #: the compiled path could attempt died this way.
    #:
    #: Declared in the schema, never inferred, and the mirrored value is
    #: recorded as ``derived`` rather than ``stated``: one plate is a fact about
    #: the family, and which slot it came from stays on the record.
    mirrors: str = "" 


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
            requires_any=tuple(spec.get("requires_any") or ()),
            mirrors=str(spec.get("mirrors") or ""),
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
    #: Where each slot's value came from — see :mod:`orion.provenance`.
    #:
    #: Recorded here because this is the last point at which the answer is
    #: knowable. Downstream every value is a float in ``variables`` and a number
    #: the user gave is indistinguishable from one the model supplied, which is
    #: how an invented dimension came to be graded exactly as convincingly as a
    #: stated one.
    provenance: dict[str, dict] = field(default_factory=dict)
    #: Features the request asked for that this system has no slot for. Kept
    #: rather than dropped: "unsupported" and "never requested" are different
    #: facts, and losing the difference is the last silent-omission path.
    unsupported: list[dict] = field(default_factory=list)
    #: Why the model could not be reached, when that is what happened.
    #:
    #: An empty family means two very different things — "this is a spring and
    #: nothing here builds springs" or "the endpoint is down" — and the caller
    #: must not treat them alike. Without this the second silently became the
    #: first, so an outage routed the request to the model path instead of the
    #: reachable provider next in line.
    transport_error: str = ""

    @property
    def complete(self) -> bool:
        """Enough to build. Not the same as enough to fully verify.

        An unaccounted dimension used to block this, so a request with one
        number nobody could place produced no part at all — the user answered
        questions and got nothing to look at, when a plate with three of its
        four features is a better answer than silence and a question.

        It no longer blocks, because it is not a gap in what we can *build*: it
        is a gap in what we can *claim*. The number still travels, as an
        explicit unsupported record that forces the verdict below VERIFIED and
        is still asked about — see ``requirements`` and ``open_questions``.
        A missing required slot is different in kind and still blocks: without
        a length there is no plate to build at all.
        """
        return bool(self.family) and not missing(self.family, self.slots)

    @property
    def unaccounted(self) -> list[float]:
        """Dimensions the request states that no slot took.

        A missing *required* slot is a gap the schema knows about. This is the
        other kind: the request said something, the extraction did not hear it,
        and every downstream check agrees with the omission because they are all
        derived from the slots. It is the same shape of defect as a builder
        dropping a feature, one stage earlier.
        """
        from . import provenance as P

        return P.unclaimed_lengths(self.request, self.slots)

    def to_dict(self) -> dict:
        return {"request": self.request, "family": self.family,
                "slots": dict(self.slots), "asked": list(self.asked),
                "complete": self.complete, "notes": list(self.notes),
                "unsupported": list(self.unsupported),
                "provenance": dict(self.provenance)}

    def classify(self) -> dict[str, dict]:
        """Recompute the provenance of the current slots.

        Called after every change to ``slots`` rather than once at the end: an
        answer the user typed is *stated* on the strength of that answer, and a
        classification computed only against the original request would report
        it as unsourced.
        """
        from . import provenance as P

        text = self.request + "\n" + "\n".join(
            f"{name}: {value}" for name, value in self.answers)
        self.provenance = P.classify(text, self.slots, notes=self.notes)
        return self.provenance


def apply_mirrors(family: str, slots: dict) -> dict:
    """Fill slots the schema says take another's value. Idempotent.

    Only ever fills a slot the request left empty, so an explicitly different
    upright thickness always wins over the base's.
    """
    fam = FAMILIES.get(family)
    if fam is None:
        return dict(slots)
    out = dict(slots)
    for s in fam.required + fam.optional:
        if not s.mirrors:
            continue
        if out.get(s.name) is not None and out.get(s.name) != "":
            continue
        source = out.get(s.mirrors)
        if source is not None and source != "":
            out[s.name] = source
    return out


def missing(family: str, slots: dict) -> list[Slot]:
    """Required slots with no value. The completeness test, in Python.

    Optional slots are never returned: asking a user for a corner radius they
    did not mention is how an assistant becomes tiring, and the absence of a
    refinement is not the absence of information.
    """
    fam = FAMILIES.get(family)
    if fam is None:
        return []
    # A slot the schema says mirrors another is not a gap once its source has a
    # value — asking for it is asking a question the request already answered.
    slots = apply_mirrors(family, slots)

    def absent(name: str) -> bool:
        return slots.get(name) is None or slots.get(name) == ""

    # A mirrored slot whose source is also missing is not a second question:
    # answering the source fills it. Asking both would be asking the user to
    # state one plate's thickness twice.
    gaps = [s for s in fam.required
            if absent(s.name) and not (s.mirrors and absent(s.mirrors))]
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
        # A choice, not a conjunction: satisfied by any one of the alternatives.
        #
        # ...and also satisfied by a hole group, when every alternative is a
        # flat placement a group supersedes. A group carries its own placement,
        # so demanding one of the old ones as well asks the user for something
        # they have already said. Measured: the NEMA 17 bracket extracted
        # cleanly into two groups, the standards table filled `hole_d` from the
        # frame, and the interview then asked "Square bolt pattern spacing?" —
        # about a pattern that was fully specified.
        if s.requires_any and all(absent(n) for n in s.requires_any):
            if slots.get("hole_groups") and set(s.requires_any) <=                     SUPERSEDED_BY_GROUPS.get(family, frozenset()):
                continue
            dep = fam.slot(s.requires_any[0])
            if dep is not None and dep not in gaps:
                gaps.append(dep)
    return gaps


def question_for(slot: Slot) -> str:
    """One question, from the schema. Not generated, so it cannot drift."""
    return slot.prompt


def _by_question() -> dict[str, Slot]:
    """Every schema question, mapped back to the slot that asked it.

    Exact lookup rather than a parse, because ``question_for`` returns
    ``Slot.prompt`` verbatim. Across all families the prompts are distinct, so a
    question names exactly one field; the first family to claim a phrasing wins
    and the rest agree with it.
    """
    idx: dict[str, Slot] = {}
    for fam in FAMILIES.values():
        for slot in list(fam.required) + list(fam.optional):
            idx.setdefault(slot.prompt.strip().lower(), slot)
    return idx


#: An answer that carries a value and no field name. Deliberately narrow: a
#: reply long enough to be a sentence is left alone, because it can say which
#: dimension it means and a prefix would only fight it.
_BARE_QUANTITY = re.compile(
    r"^[~<>=]?\s*\d+(?:\.\d+)?\s*(?:mm|cm|m|in|inch|inches)?$", re.I
)
_BARE_WORD = re.compile(r"^[A-Za-z][\w .+-]{0,23}$")


def phrase_answer(question: str, answer: str) -> str:
    """Restate a bare answer as the field it answers.

    "6 mm" replying to "How thick should it be?" names no field, and the
    extraction that reads the merged turn has nothing to bind it to. Measured:
    the value was dropped entirely, so the same question came back *and*
    ``unclaimed_lengths`` reported "the request mentions 6 mm and I have not
    used it anywhere" — the system asking about the number it had just asked
    for. Answering a question has to advance the interview or the interview is
    a loop.

    The binding is known in Python and is not the model's to guess: the
    question came from the schema, so the field it asked about is exact. Only
    an answer with no field name of its own is rewritten, and only when the
    turn asked one question — two questions and one bare number is genuinely
    ambiguous, and inventing a binding there would be worse than asking again.
    """
    answer = (answer or "").strip()
    if not answer or not question:
        return answer
    idx = _by_question()
    asked = [
        slot
        for line in question.splitlines()
        for slot in [idx.get(line.strip().lower())]
        if slot is not None
    ]
    if len(asked) != 1:
        return answer
    slot = asked[0]
    if slot.name in answer.lower():
        return answer
    pattern = _BARE_WORD if slot.text else _BARE_QUANTITY
    if not pattern.match(answer):
        return answer
    return f"{slot.name}: {answer}"


def open_questions(iv: "Interview") -> list[str]:
    """Everything still open about this request.

    Two sources, and both have to be asked or the second is silently dropped:
    slots the schema requires and the request did not fill, and dimensions the
    request stated that no slot took.

    Only the first kind blocks a build. The second is asked *alongside* the
    part, which is how an engineer works — draw what the drawing says, and come
    back about the dimension that has no feature against it.
    """
    out = [question_for(s) for s in missing(iv.family, iv.slots)]
    for value in iv.unaccounted:
        out.append(
            f"The request mentions {value:g} mm and I have not used it "
            f"anywhere — what is that dimension?")
    return out


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


#: How a part is made, read from the request rather than asked of the model.
#:
#: These are designations in the same sense "NEMA 17" is: the word is either in
#: the request or it is not. Leaving them to the extraction did not work — a
#: prompt saying "CNC machined aluminium mounting plate ... load bearing
#: bracket" came back with ten slots filled and neither of these, because the
#: extraction prompt is overwhelmingly about numbers and a choice from a list
#: does not read as a value the request "states". Deterministic here, and the
#: same request always reads the same way.
#:
#: Ordered: the first match wins, so the more specific spelling comes first.
PROCESS_WORDS = (
    ("CNC MACHINED", "machined"),
    ("CNC MILLED", "machined"),
    ("MACHINED", "machined"),
    ("MILLED", "machined"),
    ("TURNED", "machined"),
    ("DIE CAST", "cast"),
    ("SAND CAST", "cast"),
    ("INVESTMENT CAST", "cast"),
    ("CASTING", "cast"),
    ("CAST", "cast"),
    ("3D PRINTED", "printed"),
    ("ADDITIVE", "printed"),
    ("PRINTED", "printed"),
    ("SHEET METAL", "sheet"),
    ("LASER CUT", "sheet"),
    ("FOLDED", "sheet"),
)

#: What the part is for. Only ``load_bearing`` currently obliges anything — a
#: part called load-bearing with no stated duty cannot have its strength
#: checked, and the verdict would otherwise read like one that had.
FUNCTION_WORDS = (
    ("LOAD BEARING", "load_bearing"),
    ("LOAD-BEARING", "load_bearing"),
    ("STRUCTURAL", "load_bearing"),
    ("MOUNTING", "mounting"),
    ("MOUNT", "mounting"),
    ("CLEARANCE", "clearance"),
    ("ENCLOSURE", "enclosure"),
    ("HOUSING", "enclosure"),
)


def designations(request: str, slots: dict) -> dict:
    """Standard designations read out of the request text, not sampled.

    A designation is a token, not a judgement: "NEMA 17" either appears or it
    does not. Leaving it to the extraction meant the plate size stayed unknown
    whenever the model happened not to fill the slot — measured on the very
    prompt this exists for, which returned thickness, thread and pitch and no
    frame. Anything the model *did* fill is left alone.
    """
    text = (request or "").upper().replace("-", " ")
    out = dict(slots)
    if not out.get("motor_frame"):
        m = re.search("(?:^|[^A-Z])NEMA ?([0-9]+)(?:[^0-9]|$)", text)
        if m and f"NEMA {m.group(1)}" in MOTOR_FRAMES:
            out["motor_frame"] = f"NEMA {m.group(1)}"
    if not out.get("tolerance_class"):
        # "ISO 2768-m", "ISO2768 mK", "general tolerance medium". The class
        # letter is a designation like every other token read here.
        m = re.search(r"ISO ?2768[ \-]*([FMCV])", text)
        if m:
            out["tolerance_class"] = m.group(1).lower()
        else:
            for word, value in (("FINE TOLERANCE", "f"), ("MEDIUM TOLERANCE", "m"),
                                ("COARSE TOLERANCE", "c"),
                                ("GENERAL TOLERANCE FINE", "f"),
                                ("GENERAL TOLERANCE MEDIUM", "m"),
                                ("GENERAL TOLERANCE COARSE", "c")):
                if word in text:
                    out["tolerance_class"] = value
                    break
    if out.get("critical_tolerance") is None:
        # A called-out band: "+/-0.05", "±0.05 mm", "0.05 mm tolerance".
        m = re.search(r"(?:\+/-|±|\+\-)\s*([0-9]*\.?[0-9]+)", request or "")
        if m is None:
            m = re.search(r"([0-9]*\.?[0-9]+)\s*MM TOLERANCE", text)
        if m:
            try:
                out["critical_tolerance"] = float(m.group(1))
            except ValueError:
                pass
    if not out.get("datum"):
        m = re.search(
            r"(?:MEASURED|DIMENSIONED|DATUM(?:ED)?)[^.]{0,20}?FROM THE "
            r"([A-Z]+(?: [A-Z]+)?) FACE", text)
        if m is None:
            m = re.search(r"DATUM (?:IS|=) THE ([A-Z]+(?: [A-Z]+)?) FACE", text)
        if m:
            out["datum"] = f"{m.group(1).lower()} face"
    for name, table in (("process", PROCESS_WORDS), ("function", FUNCTION_WORDS)):
        if out.get(name):
            continue
        for word, value in table:
            if re.search(rf"(?:^|[^A-Z]){word}(?:[^A-Z]|$)", text):
                out[name] = value
                break
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

    # A group carries its own diameter, so a table fill for the same pattern is
    # a duplicate at a *different* number. Measured on the NEMA 17 bracket: the
    # user said 3.5, the frame table filled hole_d = 3.4, and the obligation
    # raised from the table then failed against the 3.5 holes the group had
    # correctly built. The geometry was right and the verdict said REFUSED.
    superseded = (SUPERSEDED_BY_GROUPS.get(family, frozenset())
                  if slots.get("hole_groups") else frozenset())

    def wanted(name: str) -> bool:
        if name in superseded:
            return False
        return fam is None or fam.slot(name) is not None

    out = dict(slots)
    notes: list[str] = []

    # A group may name a thread instead of a diameter, and usually does: "four
    # M5 clearance holes" states a size the model must not answer from memory.
    # Resolved here, from the same ISO 273 table the flat slots use, so the
    # structured form is not worse at standards than the form it replaces —
    # measured, two bench rows had their whole pattern reported as "no diameter
    # was given for this hole group" while the thread sat right there in it.
    for group in out.get("hole_groups") or []:
        if not isinstance(group, dict) or group.get("diameter") is not None:
            continue
        named = str(group.get("thread") or "").upper().replace(" ", "")
        if named in CLEARANCE:
            group["diameter"] = CLEARANCE[named]
            notes.append(
                f"{named} clearance hole is {CLEARANCE[named]} mm (ISO 273 "
                f"medium), so {group.get('id', 'a hole group')} = "
                f"{CLEARANCE[named]} mm")

    thread = str(out.get("thread") or out.get("hole_thread") or "").upper()
    # A named motor frame fixes the plate it bolts to. Only ever fills what the
    # request left open, so a stated size always wins over the table.
    frame = str(out.get("motor_frame") or "").upper().replace("-", " ").strip()
    if frame in MOTOR_FRAMES:
        face, square, screw = MOTOR_FRAMES[frame]
        for axis in ("length", "width"):
            if out.get(axis) is None and wanted(axis):
                out[axis] = face
                notes.append(f"{frame} face is {face} mm across (NEMA ICS 16), "
                             f"so {axis} = {face}")
        if wanted("hole_pitch"):
            if out.get("hole_pitch") is None:
                out["hole_pitch"] = square
                notes.append(f"{frame} bolt square is {square} mm "
                             f"(NEMA ICS 16), so hole_pitch = {square}")
            # A motor face carries four screws at the corners of a square, so
            # the counts follow from the frame whoever supplied the pitch. The
            # request states "31 x 31 mm square bolt pattern" and was still
            # asked how many holes across — about a pattern it had named.
            if out.get("hole_cols") is None and out.get("hole_rows") is None:
                out["hole_cols"] = out["hole_rows"] = 2
                notes.append(f"{frame} mounts on four screws in a square, "
                             f"so hole_cols = 2 and hole_rows = 2")
        if out.get("thread") is None and out.get("hole_d") is None:
            thread = screw
            notes.append(f"{frame} uses {screw} mounting screws (NEMA ICS 16)")

    if thread in CLEARANCE and out.get("hole_d") is None and wanted("hole_d"):
        out["hole_d"] = CLEARANCE[thread]
        notes.append(f"{thread} clearance hole = {CLEARANCE[thread]} mm (ISO 273 medium)")
    # A counterbore is only looked up for a counterbore the request asked for.
    #
    # Naming a thread implies a clearance hole — that is what the table above
    # is for — but it does not imply a counterbore, which is a design choice.
    # Filling one in from the thread alone invented a feature: "L bracket ...
    # M8 holes" acquired an ISO 7046 counterbore, and because ``cbore_d``
    # requires ``cbore_depth`` the interview then refused to build anything
    # until the user answered "Counterbore depth?" about a feature they had
    # never mentioned. A stated depth is the signal that they want one; the
    # standard then supplies its diameter, which is a lookup rather than a guess.
    if (thread in COUNTERBORE and out.get("cbore_d") is None
            and out.get("cbore_depth") is not None and wanted("cbore_d")):
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
it. Castings, weldments, sheet-metal bends and anything not listed are "other".

"disc" is any part turned from round stock, whatever it is called: washers,
plain cylinders, tubes and sleeves, spacers, shaft collars, pulley blanks,
flanges, cover discs and grilles are all discs — optionally bored, optionally
holed. Length does not disqualify one: a 40 mm long tube is a disc.

Two families say "bearing" and they are different requests. A "bearing_housing"
is the block that carries a bearing: a bore, a body around it, mounting holes.
A "bearing_stack" is the bearing itself on its shaft: a bore, ring thickness, a
ball gap, a width, a shaft length. Ring or ball dimensions mean bearing_stack;
a block to bolt down means bearing_housing. A rolling bearing, a shaft running
in a bearing, and a bearing named by catalogue number ("6206", "608") are all
bearing_stack — being a size you could also buy does not make it "other".

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
#:
#: The last two rules exist because a *reasoning* model does not fail an
#: ambiguous mapping — it deliberates about it, unboundedly. K2-Think-v2 given
#: "L bracket 80 x 60 legs, 50 wide, 6 thick" spent 63,219 characters and the
#: entire 16,384-token cap arguing with itself over which number was the base,
#: and emitted no answer at all; raising the budget only bought more argument.
#: Naming the dimension-order convention settles the common case, and licensing
#: omission settles the rest — the interview asking one question is the correct
#: outcome for a genuinely ambiguous request, and it is the outcome the rest of
#: this module is built around. Measured across eight requests: 7 complete, 1
#: asking, none looping, and the worst case fell from 29.2s to 7.3s.
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
- Dimensions written as "A x B x C" are given in the order length x width x \
height (height being thickness for a flat plate). Read them in that order; do \
not deliberate about which is which.
- Do not deliberate. Read the request once and report what it plainly states. \
If a field could plausibly take more than one of the stated numbers and no rule \
above settles it, OMIT it: an omitted field becomes a question the user answers, \
which is correct, while a guessed one becomes a part they did not ask for.
- Numbers must be plain numbers, not strings and not expressions.

Fields for a %s:

REQUIRED (report every one the request states):
%s

OPTIONAL (report only if stated):
%s

Reply with ONE JSON object of field names to values, and nothing else."""


#: Slots :func:`designations` reads out of the request text, so the extraction
#: never needs to be asked for them.
#:
#: Keeping them in the prompt was not merely redundant, it was destructive.
#: Measured on the NEMA 17 bracket against K2-Horizon, same request, same
#: budget of 8192 tokens::
#:
#:     29 fields   218.3 s   finish=length   60,758 chars of reasoning   0 keys
#:     24 fields   106.2 s   finish=stop     12,170 chars               12 keys
#:
#: Every optional field is something to deliberate about, and a reasoning model
#: deliberates about all of them before it writes anything. Five soft fields —
#: a process, a function, a tolerance class, a band and a datum, none of which
#: is a dimension — cost five times the reasoning and the entire answer: the
#: reply ran out of budget mid-thought and every stated dimension of a fully
#: specified bracket was lost. They are read from the text deterministically
#: anyway, which is both cheaper and repeatable.
READ_DETERMINISTICALLY = frozenset({
    "motor_frame", "process", "function",
    "tolerance_class", "critical_tolerance", "datum",
})


def extract_prompt(family: str) -> str:
    """The extraction system prompt for one family, naming its slots.

    Only the slots a model has to read. Anything :func:`designations` recovers
    from the request text is left out — see :data:`READ_DETERMINISTICALLY`.
    """
    fam = FAMILIES[family]

    # A slot a hole group supersedes is not listed beside it: two ways to say
    # one thing is more to deliberate about, not less.
    hidden = READ_DETERMINISTICALLY | (
        SUPERSEDED_BY_GROUPS.get(family, frozenset())
        if _hole_groups_section(family) else frozenset())

    def show(slots) -> str:
        return "\n".join(
            f"  {s.name} \u2014 {s.prompt}" + (" (diameter)" if s.diameter else "")
            for s in slots if s.name not in hidden
        ) or "  (none)"

    return EXTRACT_SYSTEM % (
        family.replace("_", " "), show(fam.required),
        show(fam.optional) + _hole_groups_section(family))


#: The structured field, described from the capability registry so the prompt
#: and what the builder can actually place cannot drift apart.
#:
#: Adding it *reduced* the work rather than adding to it. Measured on a plate
#: with three different hole patterns, same request, same 8192 budget:
#:
#:     flat slots    31.8s   12,282 chars   {hole_edge_gap, pcd, length,
#:                                           width, thickness}
#:     hole_groups    7.3s    1,807 chars   all three patterns, complete
#:
#: The flat form asked the model to fit three patterns through one set of
#: scalars, and it produced an edge gap and a bolt circle with no diameters
#: between them — the shape of the schema, not of the request. A field shaped
#: like what the user said is less to deliberate about, not more.
_HOLE_GROUPS_TEMPLATE = """

  hole_groups — a LIST, when the request states more than one hole pattern, or \
one that the fields above cannot hold. Each entry is an object:
    {"id": short name, "face": %s, "placement": one of below, \
"diameter": mm, plus that placement's own parameter}
    corners -> "edge_gap"; square -> "pitch"; grid -> "pitch_u"/"pitch_v"; \
bolt_circle -> "pcd" and "count".
    For a threaded size give "thread" ("M5") INSTEAD of a diameter and let the \nstandard decide it. Never convert a thread to a drill size yourself.
    Every pattern keeps its OWN diameter. Two patterns of different sizes are \
two entries, never one."""


#: Flat slots a hole group says better, per family.
#:
#: Offered *alongside* ``hole_groups`` they are the worst of both: the model
#: sees two ways to say one thing and deliberates about which, and adding the
#: structured field on top of them put the NEMA 17 bracket back over the budget
#: cliff — 277 s and not one dimension extracted. Removed instead of added to,
#: which is what "extend the vocabulary compositionally" has to mean if it is to
#: cost less rather than more.
#:
#: The schema still accepts every one of them: only the prompt changes, so a
#: stored requirements set, a regenerate, or an answer to a question keeps
#: working exactly as it did.
SUPERSEDED_BY_GROUPS: dict[str, frozenset] = {
    "rect_plate": frozenset({
        "hole_count", "hole_d", "hole_edge_gap", "pcd", "hole_pitch",
        "hole_cols", "hole_rows",
    }),
    "l_bracket": frozenset({
        "hole_d", "bolt_square", "base_hole_d", "base_hole_edge_gap",
        "base_hole_pitch_x", "base_hole_pitch_y",
    }),
}


def _hole_groups_section(family: str) -> str:
    """The hole-group field for a family that has drillable faces, or ""."""
    from . import holes as H

    faces = H.FACES.get(family)
    if not faces:
        return ""
    return _HOLE_GROUPS_TEMPLATE % " | ".join(sorted(faces))


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


#: Keys a model sometimes returns that describe the *request* rather than the
#: part. Reporting these as unsupported features would bury the real ones.
_NOT_A_FEATURE = frozenset({
    "family", "part", "part_type", "type", "name", "label", "notes", "note",
    "description", "summary", "reasoning", "rationale", "units", "unit",
    "quantity", "confidence", "assumptions", "comment",
})

#: Longer than this and the value is prose, not a dimension a builder could
#: ever have consumed.
_MAX_FEATURE_VALUE = 40


def _known_slots(family: str, raw: dict) -> tuple[dict, list[dict]]:
    """``(slots the schema declares, features it does not)``.

    A value under a name no family declares cannot reach a template — but
    dropping it silently was the last way for a requested feature to vanish
    without trace. "unsupported" and "never asked for" are different facts and
    downstream they looked identical, which is precisely the confusion the
    obligation layer exists to prevent.

    So the unrecognised ones are *returned*, not discarded, and travel into the
    frozen contract as an explicit unsupported-capability record. No obligation
    is derived from them: this system has no builder and no observer for a
    draft angle, and inventing either would be worse than saying so.

    Metadata the model volunteers about the request itself is filtered out —
    reporting ``notes`` as an unsupported CAD feature would bury the one that
    matters.
    """
    fam = FAMILIES[family]
    names = {s.name for s in fam.required + fam.optional} | {
        "thread", "hole_thread", "port_thread"}
    out: dict = {}
    unsupported: list[dict] = []
    for k, v in raw.items():
        if v is None or v == "":
            continue
        # The one structured field. Every other slot is a scalar, and the loop
        # below coerces strings to floats and rejects anything long — which
        # would turn a list of hole groups into an unsupported feature named
        # "hole_groups". Passed through whole; ``orion.holes`` validates each
        # entry and reports the ones it cannot place.
        if k == "hole_groups" and isinstance(v, list):
            out[k] = v
            continue
        if k not in names:
            if k.lower() in _NOT_A_FEATURE:
                continue
            if isinstance(v, str) and len(v) > _MAX_FEATURE_VALUE:
                continue
            unsupported.append({
                "feature": k,
                "requested": v,
                "source": "interview",
                "reason": "no slot in part_families.yaml, so no builder and no "
                          "observer — this system cannot make or check it",
            })
            continue
        if isinstance(v, str) and k not in ("material", "thread", "hole_thread",
                                            "port_thread", "port_count",
                                            "hole_count", "inlet_thread"):
            try:
                v = float(v.strip().rstrip("mm").strip())
            except ValueError:
                continue
        out[k] = v
    return out, unsupported


#: Completion budget per call.
#:
#: The served Qwen3-32B has ``max_model_len`` 8192 — prompt *and* completion
#: together. Asking for 8192 completion tokens is therefore never satisfiable
#: and vLLM rejects the request outright, which surfaced as an empty reply and
#: read exactly like a model that had nothing to say. Leave room for the prompt.
#: Start where the answer actually arrives, and do not go past it.
#:
#: Bigger is not safer with a reasoning model — it is worse, because the model
#: deliberates to fill whatever room it is given. Measured on the NEMA 17
#: bracket against K2-Horizon, same prompt, one call each::
#:
#:      8192   64.4 s   finish=stop     23,347 chars   every field, groups too
#:     16384  144.5 s   finish=length   53,134 chars   nothing at all
#:
#: The old ladder walked straight into the second row. It began at 2048, the
#: transport doubled that to 4096 on truncation, ``_ask`` escalated to
#: :data:`REASONING_TOKENS`, and the transport doubled *that* to 16384 — four
#: calls, 281 s, and a fully specified bracket reported as missing its base
#: length. Starting at the budget that works costs one call and 64 s, and the
#: reply finishes on its own so nothing doubles it.
READ_TOKENS = int(os.environ.get("ORION_READ_TOKENS", "8192"))

#: The budget a *reasoning* model needs to reach an answer at all.
#:
#: A model that derives before it replies spends the budget on the derivation
#: and emits the JSON last. Measured on K2-Think-v2: extracting six fields from
#: one plate request costs ~2,460 completion tokens, of which ~9,800 characters
#: are reasoning and 120 are the answer. At :data:`READ_TOKENS` the reply is cut
#: off mid-thought and comes back empty, which is indistinguishable from a model
#: that read the request and found nothing in it — so a fully specified plate
#: was reported as missing its length, width and thickness.
#:
#: Equal to :data:`READ_TOKENS` now, so the retry does not raise the budget —
#: see there for why raising it loses the answer. Kept as its own name because
#: a tuned model that answers immediately would want a small READ_TOKENS and
#: this floor underneath it, and the two are different questions.
REASONING_TOKENS = int(os.environ.get("ORION_INTERVIEW_TOKENS", "8192"))

EMIT_TOKENS = 4096


def _ask(client, system: str, request: str, max_tokens: int):
    """One extraction call. ``(response, transport_error)``.

    Retries once with :data:`REASONING_TOKENS` when the reply is empty, which is
    what a reasoning model returns when the whole budget went to the derivation.
    The retry is conditional rather than the default because it is the expensive
    call, and a model fine-tuned to answer directly never needs it.
    """
    from orion_agent.harness.llm.base import LLMMessage

    msgs = [LLMMessage.system(system), LLMMessage.user(request)]

    def once(budget: int):
        resp = client.chat(msgs, max_tokens=budget, temperature=0.0)
        # A transport failure is not a classification. Adapters return it as
        # content rather than raising, so without this an unreachable endpoint
        # became "rect_plate with no dimensions" and the interview asked the
        # user how long their plate was — an outage reported as a question
        # about their request.
        if getattr(resp, "finish_reason", "") == "error":
            return resp, (resp.content or "the model could not be reached")
        return resp, ""

    resp, dead = once(max_tokens)
    if dead:
        return resp, dead
    if not (resp.content or "").strip():
        # A fresh draw at the SAME budget, not a bigger one. Raising it is what
        # loses the answer — the model deliberates to fill whatever room it is
        # given, and 16384 returned nothing on a request 8192 answered in 64s.
        #
        # The variance is real even at temperature 0: a mixture-of-experts model
        # served at scale is not bit-exact, and the same bracket extracted in
        # 34s twice and then ran past the budget on the next call. One more
        # sample costs one call and usually lands.
        resp, dead = once(max(max_tokens, REASONING_TOKENS))
        if dead:
            return resp, dead
    return resp, ""


def read_request(client, request: str, max_tokens: int = READ_TOKENS) -> Interview:
    """Two model calls: name the family, then extract against its schema.

    Split deliberately. The slot list is family-specific and listing every
    family's fields in one prompt is both enormous and an invitation to mix
    them; naming the family first means the extraction prompt contains only the
    fields that can apply.
    """
    ident, dead = _ask(client, IDENTIFY_SYSTEM, request, max_tokens)
    if dead:
        return Interview(request=request, transport_error=dead)
    if not (ident.content or "").strip():
        return Interview(request=request)

    family = str((_json_of(ident.content) or {}).get("family") or "")
    if family not in FAMILIES:
        return Interview(request=request)

    got, dead = _ask(client, extract_prompt(family), request, max_tokens)
    if dead:
        return Interview(request=request, transport_error=dead)

    raw = _json_of(got.content) or {}
    slots, unsupported = _known_slots(family, raw if isinstance(raw, dict) else {})
    slots = designations(request, slots)
    slots, notes = apply_standards(slots, family)
    iv = Interview(request=request, family=family, slots=slots, notes=notes,
                   unsupported=unsupported)
    # Classified here, against the request the model was actually shown. This
    # is the only place both are in hand: after this the slots travel on and the
    # request does not, and "did the user say 120?" stops being answerable.
    iv.classify()
    return iv


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
    iv.classify()
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
    filled = apply_mirrors(iv.family, iv.slots)
    mirrored = {k for k in filled if iv.slots.get(k) in (None, "")}
    out = {"family": iv.family, "schema_version": SCHEMA_VERSION}
    out.update(resolve(iv.family, filled))
    # Structured, so ``resolve`` leaves it alone: a group carries its own
    # diameter and halving it here would halve it twice.
    if iv.slots.get("hole_groups"):
        out["hole_groups"] = list(iv.slots["hole_groups"])
    if iv.notes:
        out["standards_applied"] = list(iv.notes)
    # Travels with the numbers, under the names the numbers now have. Left
    # behind, it would be unrecoverable: a radius in a Blueprint carries no
    # record of the diameter somebody typed, or of whether anybody typed one.
    out["provenance"] = _resolved_provenance(iv, mirrored=mirrored)
    unsupported = list(iv.unsupported)
    # A dimension the request stated and no slot took travels the same way a
    # named feature with no slot does. Both are "you asked for this and we
    # cannot make or check it", and only one of them used to be sayable.
    #
    # This is what keeps the safety property while dropping the refusal. The
    # guard exists because "Tube 40 mm OD, 32 mm ID, 60 mm long" lost the bore,
    # built as a solid bar, and graded VERIFIED — the closed form was derived
    # from the same slots that dropped it, so nothing disagreed. Carrying the
    # 32 mm here means the bar still builds, and cannot be VERIFIED: an
    # unsupported record is a warning row in the verdict by construction.
    for value in iv.unaccounted:
        unsupported.append({
            "feature": f"{value:g} mm",
            "requested": value,
            "source": "interview",
            "reason": "stated in the request and no slot took it, so no "
                      "builder placed it and no observer can check it",
        })
    if unsupported:
        out["unsupported"] = unsupported
    return out


def _resolved_provenance(iv: Interview, mirrored: set = None) -> dict:
    """Slot provenance re-keyed the way :func:`resolve` re-keys the slots."""
    from . import provenance as P

    fam = FAMILIES.get(iv.family)
    mirrored = mirrored or set()
    out: dict[str, Any] = {}
    filled = apply_mirrors(iv.family, iv.slots)
    entries = dict(iv.provenance or {})
    # A mirrored slot has no entry of its own — nothing in the text named it.
    # It is derived, and the record says which slot it was derived from, so a
    # thickness that was never typed can never read as one that was.
    for name in mirrored:
        s = fam.slot(name) if fam else None
        entries[name] = {
            "source": P.DERIVED,
            "detail": f"same plate as {s.mirrors}" if s is not None else "mirrored",
        }
    for name, entry in entries.items():
        s = fam.slot(name) if fam else None
        value = filled.get(name)
        renamed = (s is not None and s.diameter
                   and isinstance(value, (int, float)) and not isinstance(value, bool))
        out[name.removesuffix("_d") + "_r" if renamed else name] = entry
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
