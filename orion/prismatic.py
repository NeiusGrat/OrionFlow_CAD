"""Prismatic parts: plates, brackets and the holes put through them.

The shaft chain answers "what must this survive?". This one answers a different
question — "you have told me the size, is what you asked for actually makeable?"
— and the two must not be merged. A duty chain asked about a plate reads
*"a 30 mm central bore"* as a journal and selects a bearing, because everything
it knows is downstream of a load. Sharing an extractor between them is how that
happens.

So this branch derives nothing from a duty. It reads dimensions that were stated,
applies the standards that govern the features between them, and refuses when
the combination cannot be built. What it adds over handing the sentence to a
model is that every number it emits came from a table or an inequality:

* a clearance hole is **ISO 273 medium**, not a guess near the thread size;
* holes keep 1.5d to a free edge and 3d to each other, so a socket fits;
* a bolt pattern is *placed* at the pitch that was asked for, rather than
  sampled from whatever the corpus happened to contain.

That last one is the whole point. Asked for four M6 holes on a 100x60 pattern,
the model previously produced four holes at scattered coordinates with a 4 mm
diameter — plausible, unplaced, and wrong in a way no reader would catch without
measuring. There is nothing to sample here: 100x60 means +/-50 and +/-30.

**What it refuses is as important as what it emits.** A feature it can read but
cannot express is refused by name, never dropped. Silently ignoring a slot
because the target family has no slot is how a user receives a part that is
missing something they asked for and are not told about.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

from orion.skills.bolt_pattern import EDGE_DISTANCE_D, ISO_273_MEDIUM, PITCH_D

#: The corpus family this branch specifies into: a rectangular pad whose holes
#: live in the profile. ``rect_with_holes`` takes an arbitrary hole list, so a
#: central bore is simply another hole and needs no new builder.
PART_CLASS = "mount_plate"

#: Wall left between a bolt hole and the central bore. A shop rule, not a
#: standard, and labelled as one wherever it is quoted.
BORE_WALL_MM = 3.0


# --------------------------------------------------------------------------- #
# intent
# --------------------------------------------------------------------------- #
@dataclass
class PlateIntent:
    """What the request said, and what could not be read from it."""

    length_mm: Optional[float] = None
    width_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    bore_dia_mm: Optional[float] = None
    hole_count: Optional[int] = None
    thread_mm: Optional[float] = None
    pattern_x_mm: Optional[float] = None
    pattern_y_mm: Optional[float] = None
    pcd_mm: Optional[float] = None
    material: str = ""
    #: Features that were recognised but this branch cannot express. Never
    #: dropped — they become a refusal.
    unsupported: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", [])}


_NUM = r"(\d+(?:\.\d+)?)"

#: "120 x 80 x 12", with or without mm on each figure and any of x/×/*.
_LWT = re.compile(
    rf"{_NUM}\s*(?:mm)?\s*[x×*]\s*{_NUM}\s*(?:mm)?\s*[x×*]\s*{_NUM}\s*(?:mm)?",
    re.I,
)
#: "100 x 60 pattern|grid|centres" — a pitch pair, distinguished from the
#: overall size by the noun that follows it rather than by position.
_PATTERN = re.compile(
    rf"{_NUM}\s*(?:mm)?\s*[x×*]\s*{_NUM}\s*(?:mm)?\s*"
    r"(?:rectangular\s+)?(?:pattern|grid|centres|centers|pitch)",
    re.I,
)
_BORE = re.compile(
    rf"(?:ø|dia\w*\s*)?{_NUM}\s*(?:mm)?\s*(?:dia\w*\s*)?"
    r"(?:central\s+|centre\s+|center\s+|middle\s+)?bore",
    re.I,
)
_BORE_ALT = re.compile(
    rf"(?:central|centre|center)\s+bore\s+(?:of\s+)?(?:ø)?{_NUM}", re.I
)
_THREAD = re.compile(rf"\bM{_NUM}\b", re.I)
_PCD = re.compile(rf"{_NUM}\s*(?:mm)?\s*(?:pcd|bolt\s+circle)", re.I)
_THICK = re.compile(rf"{_NUM}\s*(?:mm)?\s*(?:thick|thickness)", re.I)

_WORD_COUNT = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "ten": 10,
    "twelve": 12,
}
_COUNT = re.compile(
    r"\b(two|three|four|five|six|seven|eight|ten|twelve|\d+)\s+"
    r"(?:\w+\s+){0,3}?(?:holes|bolts|fixings|fasteners)",
    re.I,
)

_MATERIALS = ("aluminium", "aluminum", "steel", "stainless", "brass", "titanium")

#: Features this branch can read but not build. Recognised deliberately so they
#: can be refused by name instead of vanishing.
_UNSUPPORTED = (
    (r"\bslots?\b", "slots"),
    (r"\bcounterbor\w+", "counterbores"),
    (r"\bcountersunk\b|\bcountersink\w*", "countersinks"),
    (r"\bpockets?\b", "pockets"),
    (r"\bfillets?\b|\bcorner\s+radi\w+|\bR\d+\s+corners?", "corner radii"),
    (r"\bchamfers?\b", "chamfers"),
    (r"\btapp?ed\b|\bthreaded\s+holes?\b", "tapped holes"),
)


def read_plate(request: str) -> PlateIntent:
    """Pull the geometry out of the sentence. Nothing is invented.

    A figure absent from the request stays absent and becomes a question later.
    A default plate thickness is a number the user never gave and will never
    think to check.
    """
    text = " " + (request or "").strip() + " "
    intent = PlateIntent()

    # The pitch pair is matched first and blanked, so the overall size cannot
    # accidentally consume it: "120 x 80 x 12 ... 100 x 60 pattern" has two
    # dimension pairs and only one of them is the plate.
    pattern = _PATTERN.search(text)
    if pattern:
        intent.pattern_x_mm = float(pattern.group(1))
        intent.pattern_y_mm = float(pattern.group(2))
        text = (
            text[: pattern.start()]
            + " " * (pattern.end() - pattern.start())
            + text[pattern.end() :]
        )

    lwt = _LWT.search(text)
    if lwt:
        intent.length_mm = float(lwt.group(1))
        intent.width_mm = float(lwt.group(2))
        intent.thickness_mm = float(lwt.group(3))
    else:
        thick = _THICK.search(text)
        if thick:
            intent.thickness_mm = float(thick.group(1))
        pair = re.search(rf"{_NUM}\s*(?:mm)?\s*[x×*]\s*{_NUM}", text, re.I)
        if pair:
            intent.length_mm = float(pair.group(1))
            intent.width_mm = float(pair.group(2))

    bore = _BORE.search(text) or _BORE_ALT.search(text)
    if bore:
        intent.bore_dia_mm = float(bore.group(1))

    thread = _THREAD.search(text)
    if thread:
        intent.thread_mm = float(thread.group(1))

    pcd = _PCD.search(text)
    if pcd:
        intent.pcd_mm = float(pcd.group(1))

    count = _COUNT.search(text)
    if count:
        raw = count.group(1).lower()
        intent.hole_count = _WORD_COUNT.get(raw, None)
        if intent.hole_count is None:
            try:
                intent.hole_count = int(raw)
            except ValueError:
                intent.hole_count = None

    for word in _MATERIALS:
        if re.search(rf"\b{word}\b", text, re.I):
            intent.material = word
            break

    for rx, name in _UNSUPPORTED:
        if re.search(rx, text, re.I):
            intent.unsupported.append(name)

    return intent


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #
_PLATE_WORDS = re.compile(
    r"\b(plate|bracket|panel|flange\s+plate|base\s*plate|mounting\s+plate|"
    r"cover|gusset)\b",
    re.I,
)


def applies(request: str) -> tuple[bool, str]:
    """Whether this branch has positive evidence that it is the right one.

    Two independent signals, both required: the request names a prismatic part,
    **and** it states three overall dimensions. Either alone is not enough — a
    "bracket" with no sizes is a design problem this branch cannot start, and
    three numbers with no noun could be anything.

    Deliberately conservative. The cost of claiming a request that is not ours
    is a refusal the user cannot act on; the cost of declining one that is, is
    the behaviour they already had.
    """
    intent = read_plate(request)
    named = bool(_PLATE_WORDS.search(request or ""))
    sized = None not in (intent.length_mm, intent.width_mm, intent.thickness_mm)

    if named and sized:
        return True, (
            f"the request names a plate and states "
            f"{intent.length_mm:g} x {intent.width_mm:g} x "
            f"{intent.thickness_mm:g} mm, so its dimensions are given rather "
            f"than derived"
        )
    if named and not sized:
        return False, (
            "a prismatic part is named but its overall size is not "
            "stated, so there is nothing to specify from"
        )
    return False, "the request does not name a prismatic part"


# --------------------------------------------------------------------------- #
# specification
# --------------------------------------------------------------------------- #
@dataclass
class PlateSpec:
    """A resolved plate. Shaped to match ``reasoning.Chain`` so the router and
    the studio can treat both branches identically."""

    request: str
    part_class: str = PART_CLASS
    variables: dict[str, float] = field(default_factory=dict)
    rationale: dict[str, str] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    intent: Optional[PlateIntent] = None
    _asks: list[str] = field(default_factory=list)
    stopped_at: str = "specification"

    @property
    def complete(self) -> bool:
        return bool(self.part_class and self.variables and not self._asks)

    def asks(self) -> list[str]:
        return list(self._asks)

    def to_dict(self) -> dict:
        return {
            "request": self.request,
            "branch": "prismatic",
            "complete": self.complete,
            "stopped_at": self.stopped_at,
            "part_class": self.part_class,
            "variables": self.variables,
            "rationale": self.rationale,
            "citations": self.citations,
            "warnings": self.warnings,
            "intent": self.intent.to_dict() if self.intent else {},
            "asks": self._asks,
        }

    def explain(self) -> str:
        lines = [f"REQUEST: {self.request}", "", "PRISMATIC BRANCH"]
        if self.intent:
            lines.append(f"  read: {self.intent.to_dict()}")
        if self.complete:
            lines.append(f"SPECIFICATION ({self.part_class})")
            for k, v in sorted(self.variables.items()):
                lines.append(f"  {k} = {v:g}   {self.rationale.get(k, '')}".rstrip())
            if self.citations:
                lines.append("  per: " + "; ".join(self.citations))
        else:
            lines.append(f"INCOMPLETE — stopped at {self.stopped_at}")
        for q in self._asks:
            lines.append(f"  ASKS: {q}")
        for w in self.warnings:
            lines.append(f"NOTE: {w}")
        return "\n".join(lines)


def specify(request: str) -> PlateSpec:
    """Stated dimensions plus applied standards, or the reason there is no part."""
    intent = read_plate(request)
    spec = PlateSpec(request=request, intent=intent)

    if None in (intent.length_mm, intent.width_mm, intent.thickness_mm):
        spec._asks.append(
            "State the plate as length x width x thickness — all three are "
            "needed and none can be assumed."
        )
        spec.stopped_at = "intent"
        return spec

    # A feature read but not expressible is refused by name. Dropping it would
    # hand back a part missing something the user asked for, with nothing in the
    # output to say so.
    if intent.unsupported:
        spec._asks.append(
            "This branch builds a plate with round holes only; it cannot yet "
            "place "
            + ", ".join(sorted(set(intent.unsupported)))
            + ". Remove them, or design the plate without them first."
        )
        spec.stopped_at = "specification"
        return spec

    pl, pw, pt = intent.length_mm, intent.width_mm, intent.thickness_mm
    v: dict[str, float] = {"pl": pl, "pw": pw, "pt": pt}
    spec.rationale.update(
        {
            "pl": "stated length",
            "pw": "stated width",
            "pt": "stated thickness",
        }
    )

    # ---- central bore ---------------------------------------------------- #
    if intent.bore_dia_mm:
        pb_r = intent.bore_dia_mm / 2.0
        if pb_r >= min(pl, pw) / 2.0:
            spec._asks.append(
                f"a {intent.bore_dia_mm:g} mm bore does not fit in a "
                f"{pl:g} x {pw:g} mm plate — it is wider than the plate itself"
            )
            return spec
        v["pb_r"] = pb_r
        spec.rationale["pb_r"] = f"stated {intent.bore_dia_mm:g} mm central bore"

    # ---- bolt pattern ----------------------------------------------------- #
    if intent.hole_count or intent.thread_mm or intent.pattern_x_mm:
        if intent.pcd_mm and not intent.pattern_x_mm:
            spec._asks.append(
                "a bolt circle on a rectangular plate is not handled by this "
                "branch yet; state the pattern as a rectangular pitch, e.g. "
                "'on a 100 x 60 pattern'"
            )
            return spec
        if not intent.thread_mm:
            spec._asks.append(
                "What size are the fasteners? The clearance hole comes from "
                "ISO 273 and cannot be derived from the pattern alone."
            )
            return spec
        if intent.thread_mm not in ISO_273_MEDIUM:
            spec._asks.append(
                f"no ISO 273 clearance hole is tabulated for "
                f"M{intent.thread_mm:g}. Available: "
                + ", ".join(f"M{d:g}" for d in sorted(ISO_273_MEDIUM))
            )
            return spec
        if None in (intent.pattern_x_mm, intent.pattern_y_mm):
            spec._asks.append(
                "Where do the holes go? State the pattern as a rectangular "
                "pitch, e.g. 'on a 100 x 60 pattern'."
            )
            return spec
        if intent.hole_count not in (None, 4):
            spec._asks.append(
                f"a rectangular pattern places four holes, one per corner; "
                f"{intent.hole_count} was asked for"
            )
            return spec

        d = intent.thread_mm
        hole_dia = ISO_273_MEDIUM[d]
        hr = hole_dia / 2.0
        mx = intent.pattern_x_mm / 2.0
        my = intent.pattern_y_mm / 2.0

        refusals, cautions = _check_pattern(pl, pw, mx, my, hr, d, v.get("pb_r"))
        if refusals:
            spec._asks.extend(refusals)
            return spec
        spec.warnings.extend(cautions)

        v.update({"hr": hr, "mx": mx, "my": my})
        spec.rationale.update(
            {
                "hr": f"M{d:g} clearance hole {hole_dia:g} mm (ISO 273 medium)",
                "mx": f"half of the stated {intent.pattern_x_mm:g} mm pitch",
                "my": f"half of the stated {intent.pattern_y_mm:g} mm pitch",
            }
        )
        spec.citations.append(
            f"ISO 273 medium series: M{d:g} clearance hole {hole_dia:g} mm"
        )
        spec.citations.append(
            f"edge distance {EDGE_DISTANCE_D:g}d and pitch {PITCH_D:g}d "
            f"(shop convention, not a standard)"
        )

    if intent.material:
        # Recorded, never geometric. The Blueprint has no material field, and
        # inventing one here would put a fact in the model that nothing checks.
        spec.warnings.append(
            f"{intent.material} is noted but not represented: the Blueprint "
            f"carries geometry only, so material is not verified"
        )

    spec.variables = {k: round(float(x), 4) for k, x in v.items()}
    return spec


def _check_pattern(pl, pw, mx, my, hr, d, pb_r) -> tuple[list[str], list[str]]:
    """``(refusals, cautions)`` for a pattern on a plate.

    The split is the point, and it follows what the rule *is*. Geometry that
    cannot exist — a hole off the edge of the plate, or one that opens into the
    central bore — is refused: there is no part to build, and building the
    nearest thing would hand back something the user did not ask for.

    A shop convention is a different claim. ``EDGE_DISTANCE_D`` and ``PITCH_D``
    are multiples of the bolt diameter that keep a socket usable and a boss from
    tearing out; ``orion/skills/bolt_pattern.py`` labels them "conventions rather
    than a standard" and it is right to. Refusing a plate because it is 2 mm
    tighter than a rule of thumb would reject the drawing on the user's desk.
    They are reported instead, with the arithmetic, and the part is built.
    """
    refuse: list[str] = []
    caution: list[str] = []
    edge = EDGE_DISTANCE_D * d

    x_edge = pl / 2.0 - mx - hr
    y_edge = pw / 2.0 - my - hr

    # Off the plate entirely: not tight, impossible.
    for gap, span, axis in ((x_edge, pl, "length"), (y_edge, pw, "width")):
        if gap <= 0:
            refuse.append(
                f"the holes fall outside the plate: a "
                f"{2 * (mx if axis == 'length' else my):g} mm pitch with "
                f"{2 * hr:g} mm holes needs more than {span:g} mm of {axis}"
            )
    if refuse:
        return refuse, caution

    if x_edge < edge:
        caution.append(
            f"a {2 * mx:g} mm pitch on a {pl:g} mm plate leaves {x_edge:.1f} mm "
            f"from hole to edge; {edge:.1f} mm ({EDGE_DISTANCE_D:g}d) is the "
            f"usual minimum for M{d:g}. Widening the plate to "
            f"{2 * (mx + hr + edge):.0f} mm would clear it. Shop convention, "
            f"not a standard — built as asked."
        )
    if y_edge < edge:
        caution.append(
            f"a {2 * my:g} mm pitch on a {pw:g} mm plate leaves {y_edge:.1f} mm "
            f"from hole to edge; {edge:.1f} mm ({EDGE_DISTANCE_D:g}d) is the "
            f"usual minimum for M{d:g}. Deepening the plate to "
            f"{2 * (my + hr + edge):.0f} mm would clear it. Shop convention, "
            f"not a standard — built as asked."
        )

    min_pitch = PITCH_D * d
    for span, axis in ((2 * mx, "x"), (2 * my, "y")):
        if span < min_pitch:
            caution.append(
                f"the holes are {span:g} mm apart in {axis}; {min_pitch:.1f} mm "
                f"({PITCH_D:g}d) is the usual minimum for socket access. Shop "
                f"convention, not a standard — built as asked."
            )

    if pb_r is not None:
        gap = math.hypot(mx, my) - pb_r - hr
        if gap <= 0:
            # The hole and the bore intersect. Two features become one opening
            # and the part is no longer the one described.
            refuse.append(
                f"the bolt holes open into the central bore — a "
                f"{2 * pb_r:g} mm bore and a "
                f"{2 * math.hypot(mx, my):.0f} mm diagonal pitch overlap by "
                f"{-gap:.1f} mm. Open the pattern or reduce the bore."
            )
        elif gap < BORE_WALL_MM:
            caution.append(
                f"only {gap:.1f} mm of wall between the bolt holes and the "
                f"central bore; {BORE_WALL_MM:g} mm is the usual minimum. Shop "
                f"convention, not a standard — built as asked."
            )
    return refuse, caution


# --------------------------------------------------------------------------- #
# hand-off
# --------------------------------------------------------------------------- #
def design_prompt(spec: PlateSpec) -> str:
    """What the Blueprint model is given: dimensions, in its own register.

    Same contract as the shaft branch — the numbers are settled, and the
    reasoning is withheld because it belongs to the user. The variable names are
    the ones the ``mount_plate`` family already uses in training, so this reads
    as a resolved part rather than as a new vocabulary.
    """
    if not spec.complete:
        raise ValueError(f"spec stopped at {spec.stopped_at}; nothing to build")
    dims = ", ".join(f"{k}={v:g}" for k, v in sorted(spec.variables.items()))
    return f"Build a {spec.part_class} with {dims}."
