"""What the dimensions are allowed to be, and whether the process can hold it.

A drawing without tolerances is not a drawing — every dimension on it is a wish.
Until now every number this system produced was exact and unqualified, which is
the same thing: "120 mm" with nothing after it means the shop applies its own
general tolerance and nobody has agreed what the part is.

Three things are checked here, and each is a different kind of claim:

**The schedule.** ISO 2768-1 is a real table, not a rule of thumb: given a
general tolerance class it says exactly what every unstated dimension is
allowed to be, keyed on nominal size. So the schedule is computed and reported
as evidence — the 120 mm length of an ISO 2768-m part is 120 +/- 0.3, and
saying so costs nothing and settles an argument.

**Achievability.** A tolerance is a claim about a process. +/-0.05 on a sand
casting is not a tight tolerance, it is a fiction, and the part will be
rejected at inspection for a number somebody typed without meaning it. The
process floors here are economical figures — what a shop holds without extra
operations — and they are rules of thumb, so they say so.

**The datum frame.** A size tolerance needs no datum: a diameter is a diameter
measured anywhere. A *position* does. Calling out +/-0.05 on where a hole sits,
with nothing to measure from, is not a tight tolerance either — it is an
incomplete one, and the two failure modes look identical on a drawing.

Nothing here fails a part, for the same reason nothing in :mod:`orion.dfm`
does: REFUSED belongs to the geometry disagreeing with its own frozen
prediction. A tolerance nobody can hold is a conversation, not a defect in the
model.
"""

from __future__ import annotations

import re
from typing import Any, Optional

PASS = "pass"
WARN = "warn"

#: ISO 2768-1, permissible deviations for linear dimensions, in millimetres.
#:
#: ``(upper_bound_exclusive, {class: deviation})`` walked in order; the first
#: band whose bound the nominal is under wins. ``None`` means the standard
#: gives no value for that class in that band, which is a real gap and not a
#: zero — the coarsest class starts at 3 mm because below that it is meaningless.
_ISO_2768 = (
    (3.0, {"f": 0.05, "m": 0.1, "c": 0.2, "v": None}),
    (6.0, {"f": 0.05, "m": 0.1, "c": 0.3, "v": 0.5}),
    (30.0, {"f": 0.1, "m": 0.2, "c": 0.5, "v": 1.0}),
    (120.0, {"f": 0.15, "m": 0.3, "c": 0.8, "v": 1.5}),
    (400.0, {"f": 0.2, "m": 0.5, "c": 1.2, "v": 2.5}),
    (1000.0, {"f": 0.3, "m": 0.8, "c": 2.0, "v": 4.0}),
    (2000.0, {"f": 0.5, "m": 1.2, "c": 3.0, "v": 6.0}),
    (4000.0, {"f": None, "m": 2.0, "c": 4.0, "v": 8.0}),
)

CLASSES = {"f": "fine", "m": "medium", "c": "coarse", "v": "very coarse"}

#: What a process holds *economically* — without a second setup, grinding, or
#: 100% inspection. Rules of thumb, and said to be.
_PROCESS_FLOOR = {
    "machined": 0.05,
    "cast": 0.5,
    "printed": 0.2,
    "sheet": 0.2,
}


def deviation(nominal: float, cls: str) -> Optional[float]:
    """The ISO 2768-1 permissible deviation for one dimension, or ``None``.

    ``None`` where the standard gives no value: under 0.5 mm it does not apply,
    and the table has real gaps at the extremes of the coarse and fine classes.
    """
    if nominal is None or nominal < 0.5:
        return None
    for bound, row in _ISO_2768:
        if nominal < bound:
            return row.get(cls)
    return None


def schedule(variables: dict, cls: str) -> dict:
    """``{variable: deviation}`` for every linear dimension a part carries.

    Radii are reported as they are stored. A radius tolerance is half the
    diameter tolerance and converting here would report a number the drawing
    does not carry.
    """
    out: dict[str, float] = {}
    for name, value in sorted((variables or {}).items()):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        dev = deviation(float(value), cls)
        if dev is not None:
            out[name] = dev
    return out


#: Words that name a kind of geometry rather than which one. "top face" and
#: "bottom face" differ by exactly one word and it is not this one.
_GENERIC = frozenset({
    "face", "faces", "surface", "plane", "edge", "side", "the", "a", "of",
    "primary", "secondary", "tertiary", "datum", "from", "and", "mm",
})


def _distinguishing(text: str) -> set:
    """The words in a datum description that say *which* face it is."""
    words = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {w for w in words if w and w not in _GENERIC and not w.isdigit()}


def _row(rid: str, label: str, status: str, detail: str,
         basis: str, evidence: Optional[dict] = None) -> dict:
    return {
        "id": f"tolerance:{rid}",
        "label": label,
        "status": status,
        "detail": detail,
        "evidence": {"basis": basis, **(evidence or {})},
    }


def _datum_rows(decl: dict, datums: dict) -> list[dict]:
    named = str(decl.get("datum") or "").strip().lower()
    critical = decl.get("critical")
    frame = {k: str(v) for k, v in (datums or {}).items()}
    out = []

    if critical and len(frame) < 3:
        # Three datums, not one. A primary face removes three degrees of
        # freedom, a secondary edge two, a tertiary one — six between them, and
        # anything short of that leaves the feature free to move in the
        # direction nobody constrained. These parts declare two, so a called-out
        # position is locked in five directions and floating in the sixth.
        #
        # A size tolerance needs none of this: a diameter is a diameter measured
        # anywhere. The two are indistinguishable on a drawing, which is exactly
        # why it is worth saying out loud.
        out.append(_row(
            "datum_frame",
            "A called-out tolerance has something to measure from",
            WARN,
            f"+/-{critical:g} mm is called out and this part declares "
            f"{len(frame)} datum(s): {', '.join(sorted(frame)) or 'none'}. "
            f"A size tolerance needs none, but locating a feature takes three "
            f"— a face, an edge and a stop — and two leaves it free in the "
            f"direction nobody constrained.",
            "a datum reference frame removes six degrees of freedom: 3 + 2 + 1",
            {"datums": frame, "critical": critical},
        ))

    if named:
        # Does the face the user calls the datum match the one the part is
        # actually dimensioned from? A part built off its bottom face and
        # inspected off its top face is measured through every tolerance in
        # between.
        primary = ""
        for key in sorted(frame):
            if "primary" in frame[key].lower():
                primary = frame[key]
                break
        primary = primary or frame.get("A", "")
        # Compare what distinguishes the faces, not the noun they share.
        # Matching on any word meant "top face" agreed with "bottom face
        # z=0 (primary)" because both contain "face", so the one comparison
        # this rule exists to make was the one it could not make.
        stated = _distinguishing(named)
        declared = _distinguishing(primary)
        if primary and stated and not (stated & declared):
            out.append(_row(
                "datum_agrees",
                "The stated datum is the one the part is dimensioned from",
                WARN,
                f"you called the {named} the datum, and this part is "
                f"dimensioned from the {primary}. A part built off one face "
                f"and inspected off another is measured through every "
                f"tolerance in between.",
                "the datum is where the dimensions originate, not where the "
                "part is convenient to hold",
                {"stated": named, "declared_primary": primary},
            ))
    return out


def check(design_plan: Optional[dict], variables: Optional[dict] = None,
          datums: Optional[dict] = None) -> list[dict]:
    """Tolerance rows for the frozen ``tolerance`` declaration.

    ``[]`` when a design said nothing about tolerances, which is every part
    that does not carry them — the same rule as every other evidence layer
    here: silence is not an invitation to guess.
    """
    decl = (design_plan or {}).get("tolerance")
    if not isinstance(decl, dict) or not decl:
        return []
    variables = variables or {}
    process = str((((design_plan or {}).get("manufacturing")) or {})
                  .get("process") or "").strip().lower()
    floor = _PROCESS_FLOOR.get(process)

    rows: list[dict] = []
    cls = str(decl.get("class") or "").strip().lower()
    if cls and cls not in CLASSES:
        rows.append(_row(
            "class_known",
            "The general tolerance class is one ISO 2768 defines",
            WARN,
            f"{cls!r} is not an ISO 2768 class. Known: "
            + ", ".join(f"{k} ({v})" for k, v in CLASSES.items()) + ".",
            "ISO 2768-1 defines exactly four classes",
            {"class": cls},
        ))
        cls = ""

    if cls:
        sched = schedule(variables, cls)
        if sched:
            worst = min(sched.values())
            rows.append(_row(
                "schedule",
                f"General tolerances resolved: ISO 2768-{cls}",
                PASS,
                "every dimension without its own tolerance is held to "
                f"ISO 2768-{cls} ({CLASSES[cls]}); the tightest that leaves is "
                f"+/-{worst:g} mm. "
                + ", ".join(f"{k} +/-{v:g}" for k, v in
                            sorted(sched.items(), key=lambda kv: -kv[1])[:6]),
                "ISO 2768-1 table of permissible deviations for linear "
                "dimensions",
                {"class": cls, "schedule": sched, "tightest": worst},
            ))
            if floor is not None and worst < floor:
                rows.append(_row(
                    "class_process",
                    "The general tolerance is one the process can hold",
                    WARN,
                    f"ISO 2768-{cls} asks for +/-{worst:g} mm on this part's "
                    f"smallest dimensions and {process} holds about "
                    f"+/-{floor:g} mm economically. Either loosen the class or "
                    f"expect the extra operations.",
                    f"typical economical tolerance for {process}, without a "
                    f"second setup or grinding",
                    {"class": cls, "required": worst, "process_floor": floor},
                ))

    critical = decl.get("critical")
    if critical is not None and floor is not None and critical < floor:
        rows.append(_row(
            "critical_process",
            "The called-out tolerance is one the process can hold",
            WARN,
            f"+/-{critical:g} mm is called out and {process} holds about "
            f"+/-{floor:g} mm economically. On a casting a number like this is "
            f"not a tight tolerance, it is one the part will be rejected "
            f"against."
            if process == "cast" else
            f"+/-{critical:g} mm is called out and {process} holds about "
            f"+/-{floor:g} mm economically. It is achievable with extra "
            f"operations and inspection; it is not free.",
            f"typical economical tolerance for {process}",
            {"critical": critical, "process_floor": floor},
        ))

    rows += _datum_rows(decl, datums or {})
    return rows
