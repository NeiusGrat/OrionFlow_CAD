"""Where every number in a design came from — decided in Python, before the freeze.

A dimension the user stated and a dimension a model supplied are, today,
indistinguishable by the time they reach the Blueprint. They are both floats in
``variables``, and the assertions that grade the part are derived from those same
floats — so a part whose dimensions were invented passes its volume check
exactly as convincingly as one whose dimensions were given. The verdict says
VERIFIED and means "the geometry matches the numbers", but it is read as "the
numbers are right".

This module makes the difference structural. Every value carries a source:

``stated``     the request contains this number
``standard``   a table decided it, and the citation says which
``derived``    named code computed it from other values
``default``    a documented fallback was applied because nothing said otherwise
``unsourced``  nothing above accounts for it — someone or something chose it

Only the last one is a problem, and it is the one that was invisible.

**Corroboration is textual and deterministic.** A value is ``stated`` when the
request literally contains that number, allowing for the ways the same fact gets
written down: number words, unit suffixes, and the diameter/radius halving this
codebase does on the way in. It does not attempt to understand the request —
understanding is what would put a model back in the loop, and a model asked
"did the user say this?" will agree with itself.

The test is therefore literal, and its one blind spot is worth naming: a
numeral that appears in the request for some *other* reason — "NEMA 23", "a
6205 bearing", "Grade 8.8" — counts as a literal, so a variable that happens to
equal it is credited as stated. The window is narrow (the value has to match
exactly, or double, or half) and it is the only direction in which this
under-reports. Everything else it gets wrong it gets wrong the safe way: an
unusual unit or an arithmetic step the user did in their head is reported as
unsourced, which costs a line in the ledger rather than a false assurance.

The classification is computed **before** the Blueprint is frozen and lives in
``design_plan``, so it is inside ``blueprint_hash``. It therefore cannot be
back-filled once the part has been measured — the same property that keeps the
assertions honest.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

STATED = "stated"
STANDARD = "standard"
DERIVED = "derived"
DEFAULT = "default"
UNSOURCED = "unsourced"

#: Sources that account for a value. Anything else is a number nobody sourced.
ACCOUNTED = frozenset({STATED, STANDARD, DERIVED, DEFAULT})

#: Relative tolerance when matching a value against a number in the request.
#: Loose enough for the rounding a user does when they type, tight enough that
#: 10 and 12 never match.
_REL_TOL = 1e-6

#: Number words, because "four holes" is a stated count and "4" is the same
#: fact. Stops at twenty: past that people write digits.
_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
    "half": 0.5, "quarter": 0.25,
    "single": 1, "pair": 2, "dozen": 12,
}

#: Unit suffixes to millimetres. A request in centimetres states the same
#: dimension the Blueprint stores in mm, and refusing to see that would flag
#: every metric-but-not-mm request as unsourced.
_UNITS = {
    "mm": 1.0, "millimetre": 1.0, "millimeter": 1.0,
    "cm": 10.0, "centimetre": 10.0, "centimeter": 10.0,
    "m": 1000.0, "metre": 1000.0, "meter": 1000.0,
    "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4,
    "thou": 0.0254, "mil": 0.0254,
}

_NUMBER = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|millimetres?|millimeters?|"
    r"centimetres?|centimeters?|metres?|meters?|inches|inch|in\b|thou|mils?|\"|m\b)?",
    re.IGNORECASE,
)


def literals_with_units(request: str) -> list[tuple[float, str]]:
    """Every quantity the request states, each tagged with the unit it was
    written in (``""`` where it was written bare, or spelled as a word).

    The tag is what lets a caller refuse a reading the number cannot support.
    "a 30 mm bore housing" states 30, and 30 newtons is not among the things it
    states — see ``orion.duty.supported``, which uses this to stop a length
    corroborating a force.
    """
    text = (request or "").lower()
    out: list[tuple[float, str]] = []

    for word, value in _WORDS.items():
        if re.search(rf"\b{word}\b", text):
            out.append((float(value), ""))

    for match in _NUMBER.finditer(text):
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        unit = (match.group("unit") or "").strip().rstrip(".")
        out.append((value, unit))
        factor = _UNITS.get(unit)
        if factor is not None:
            out.append((value * factor, unit))

    return out


def literals(request: str) -> set[float]:
    """Every quantity the request states, in the units a Blueprint stores.

    Each numeral contributes its face value *and*, where a unit follows, that
    value converted to millimetres. Both, because a bare "120" is millimetres by
    convention here and "12 cm" is the same dimension written differently —
    admitting only one of the two readings would flag the other as unsourced.
    """
    return {value for value, _unit in literals_with_units(request)}


#: Unit tokens that mark a number as a length. Named so a caller measuring
#: something else can decline them.
LENGTH_UNITS = frozenset(_UNITS)


def unclaimed_lengths(request: str, values: Any) -> list[float]:
    """Dimensions the request states that no value accounts for.

    :func:`classify` runs one way — every value is tested against the request,
    and one with no number behind it is ``unsourced``. This is the other way,
    and nothing ran it: a number the user wrote that reached no slot simply
    disappeared. "Tube 40 mm OD, 32 mm ID, 60 mm long" was read as an outside
    diameter and a length, the bore was dropped on the floor, and the part
    built as a **solid bar** — then graded VERIFIED, because the closed form
    was derived from the same slots that lost it.

    Only numbers written with a length unit are considered. A bare numeral is
    too weak a signal — "M5", "NEMA 17" and "3 x 3" all carry integers that
    name no dimension — and a false question is a worse answer than none.
    """
    pool = [v for v in (values or {}).values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)]
    out: list[float] = []
    for value, unit in literals_with_units(request):
        if unit not in LENGTH_UNITS:
            continue
        if any(corroborated(v, [value]) for v in pool):
            continue
        if value not in out:
            out.append(value)
    return out


def _close(a: float, b: float, rel_tol: float = _REL_TOL) -> bool:
    return abs(a - b) <= rel_tol * max(1.0, abs(a), abs(b))


def corroborated(value: Any, lits: Iterable[float], rel_tol: float = _REL_TOL) -> bool:
    """Whether a numeric value is accounted for by something in the request.

    Three readings of the same statement are accepted: the number itself, twice
    it, and half it. The doubling is not generosity — ``interview.resolve``
    halves every stated diameter into a radius before a Blueprint ever sees it,
    so a bore the user gave as 20 mm arrives here as 10 and would otherwise be
    reported as a number they never mentioned.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    v = float(value)
    pool = list(lits)
    return any(
        _close(v, n, rel_tol)
        or _close(v * 2.0, n, rel_tol)
        or _close(v, n * 2.0, rel_tol)
        for n in pool
    )


def _text_stated(value: str, request: str) -> bool:
    """Whether a designation (M10, 6061, G1/4) appears in the request."""
    token = str(value).strip().lower()
    if not token:
        return False
    return re.search(re.escape(token), (request or "").lower()) is not None


def _standard_fields(notes: Iterable[str]) -> dict[str, str]:
    """Which fields ``interview.apply_standards`` filled, and from what.

    Reads the notes that function already writes rather than asking it to
    return a second structure: one source, so a substitution cannot be recorded
    in one place and missed in the other.
    """
    out: dict[str, str] = {}
    for note in notes or ():
        text = str(note)
        low = text.lower()
        # The general form, and the one new tables should use: a note that says
        # which field it filled. The three phrase matches below predate it and
        # are kept because their notes read better without the suffix.
        for field in re.findall("(?:^|[, ])so ([a-z_][a-z0-9_]*) = ", low):
            out[field] = text
        if "clearance hole" in low:
            out["hole_d"] = text
        elif "counterbore" in low:
            out["cbore_d"] = text
        elif "tapping drill" in low:
            out["port_d"] = text
    return out


def classify(
    request: str,
    values: dict[str, Any],
    notes: Optional[Iterable[str]] = None,
    defaults: Optional[dict[str, str]] = None,
    derived: Optional[dict[str, str]] = None,
) -> dict[str, dict[str, str]]:
    """``{name: {"source": ..., "basis": ...}}`` for every value given.

    ``notes`` are ``interview.apply_standards`` citations; ``defaults`` and
    ``derived`` are ``{name: why}`` from code that knows it supplied the value.
    Anything left over is tested against the request text, and what survives
    that is ``unsourced``.
    """
    lits = literals(request)
    from_standard = _standard_fields(notes or ())
    defaults = defaults or {}
    derived = derived or {}

    out: dict[str, dict[str, str]] = {}
    for name, value in (values or {}).items():
        if name in derived:
            out[name] = {"source": DERIVED, "basis": derived[name]}
        elif name in from_standard:
            out[name] = {"source": STANDARD, "basis": from_standard[name]}
        elif name in defaults:
            out[name] = {"source": DEFAULT, "basis": defaults[name]}
        elif isinstance(value, str):
            out[name] = (
                {"source": STATED, "basis": "named in the request"}
                if _text_stated(value, request)
                else {"source": UNSOURCED, "basis": "not named in the request"}
            )
        elif corroborated(value, lits):
            out[name] = {"source": STATED, "basis": "given in the request"}
        else:
            out[name] = {
                "source": UNSOURCED,
                "basis": "no number in the request accounts for this value",
            }
    return out


#: Sources ordered worst-first. Where a variable could inherit from more than
#: one requirement, it inherits the weakest — a number that is ambiguous
#: between "the user gave it" and "nobody did" has to be reported as the
#: second, or the ambiguity itself becomes a way to launder a value.
_RANK = (UNSOURCED, DEFAULT, DERIVED, STANDARD, STATED)


def extend(
    base: dict[str, dict[str, str]],
    values: dict[str, Any],
    basis: str,
    source_values: Optional[dict[str, Any]] = None,
) -> dict[str, dict[str, str]]:
    """Carry a requirement classification onto the variables a generator produced.

    Matching by name alone is not enough, and getting that wrong laundered the
    most important numbers in the part. ``blueprint_gen.rect_plate`` writes the
    stated ``length`` into a variable called ``L``; with only a name check, ``L``
    fell through to ``derived`` — so a plate whose length, width and thickness a
    model had invented reported three *derived* dimensions and passed the gate
    that exists to catch exactly that.

    So a variable inherits from a requirement of the same name, or failing that
    from one carrying the same value. What matches neither really was computed
    here: every expression in a builder is written in that module, and there is
    no step at which a free number could enter.
    """
    out = dict(base)
    sources = source_values or {}

    def by_value(value: Any) -> Optional[dict[str, str]]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        hits = [
            base[name]
            for name, other in sources.items()
            if name in base
            and not isinstance(other, bool)
            and isinstance(other, (int, float))
            and _close(float(value), float(other))
        ]
        if not hits:
            return None
        return min(hits, key=lambda e: _RANK.index(e.get("source", UNSOURCED))
                   if e.get("source") in _RANK else 0)

    for name, value in (values or {}).items():
        if name in out:
            continue
        inherited = by_value(value)
        out[name] = (
            {**inherited, "basis": inherited["basis"] + f" (as {name})"}
            if inherited
            else {"source": DERIVED, "basis": basis}
        )
    return {name: out[name] for name in (values or {}) if name in out}


def unsourced(provenance: Optional[dict]) -> list[str]:
    """The names nothing accounts for, sorted. The ledger's failing rows."""
    return sorted(
        name
        for name, entry in (provenance or {}).items()
        if (entry or {}).get("source") not in ACCOUNTED
    )


def summary(provenance: Optional[dict]) -> dict[str, int]:
    """How many values came from where. What a report leads with."""
    counts: dict[str, int] = {}
    for entry in (provenance or {}).values():
        source = (entry or {}).get("source") or UNSOURCED
        counts[source] = counts.get(source, 0) + 1
    return counts
