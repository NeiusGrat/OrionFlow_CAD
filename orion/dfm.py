"""Can this part actually be made, by the process it says it is made by.

The verdict has said three things about a part: the geometry matches its frozen
prediction, every number is accounted for, and every requested feature is
present. All three can hold for a part no shop can cut. A milled pocket with
sharp internal corners is geometrically perfect and physically impossible —
an end mill is round, and it leaves a radius whether the drawing says so or
not.

So this is a fourth dimension of evidence, and it follows the same rules as the
other three:

**Nothing is assumed.** A design that does not say how it is made gets no
manufacturability checks and is completely unaffected. Guessing "probably
milled" would put a warning on every part in the corpus and teach everyone to
ignore the row.

**The inputs are frozen.** ``blueprint_gen`` writes a ``manufacturing`` block
into ``design_plan`` — the process, and the handful of dimensions the rules
read — before the part is built, so it is inside ``blueprint_hash`` and cannot
be fitted to the result afterwards. The rules run later; the facts they run on
are committed first.

**Every rule is a warning.** Not because none of them matters — a sharp-cornered
milled pocket is a model that will not match the part that comes off the
machine — but because refusing gives the user nothing. A plate with a question
against its pocket corners beats no plate, which is the same reason an
unplaceable dimension stopped blocking a build. The strongest rule here says
"this will come out different and here is by how much", and hands back the
part.

Nothing in this module fails a part. A verdict of REFUSED means the geometry
disagreed with its own frozen prediction; how expensive it is to cut is a
different question and must not borrow that word.

Every rule states its basis. A rule of thumb that cannot say where it comes
from is someone's habit, and this file is not the place for it.
"""

from __future__ import annotations

from typing import Any, Optional

#: No ``FAIL``. Nothing here fails a part — see the note above on why
#: "refused" belongs to the geometry disagreeing with its prediction.
PASS = "pass"
WARN = "warn"

#: Smallest standard end mill a job shop keeps, in millimetres of DIAMETER.
#: Below this the tool is a specialist item and the pocket costs what the tool
#: costs. 3 mm is the common floor; 2 mm and 1 mm exist and are slow.
_SMALLEST_END_MILL_D = 3.0

#: How deep a pocket may go for a given corner radius before the tool is too
#: slender to hold a cut. Standard tooling reaches about four diameters;
#: long-reach holders roughly double it and chatter on the way.
_POCKET_DEPTH_PER_RADIUS = 4.0

#: Drilled depth in diameters before the hole needs peck cycles or a gun drill.
#: Five is where shops start charging differently.
_HOLE_DEPTH_PER_DIAMETER = 5.0

#: Minimum wall a process can hold, in mm. Cast walls are thick because metal
#: has to flow and solidify; milled walls are thin until they chatter.
_MIN_WALL = {
    "machined": 0.8,
    "cast": 3.0,
    "printed": 0.8,
    "sheet": 0.5,
}

#: Processes this file knows rules for. Anything else is recorded and produces
#: no rows — an unknown process is not a licence to apply the milling rules.
PROCESSES = frozenset(_MIN_WALL)


def _row(rid: str, label: str, status: str, detail: str,
         basis: str, evidence: Optional[dict] = None) -> dict:
    return {
        "id": f"manufacturing:{rid}",
        "label": label,
        "status": status,
        "detail": detail,
        "evidence": {"basis": basis, **(evidence or {})},
    }


def _pocket_rules(process: str, f: dict) -> list[dict]:
    pocket = f.get("pocket")
    if not isinstance(pocket, dict):
        return []
    depth = pocket.get("depth")
    r = pocket.get("corner_radius") or 0.0
    if depth is None:
        return []
    out = []
    if process == "machined":
        if not r:
            # The strongest rule here, and still a warning. A rotating tool
            # cannot produce a zero-radius internal corner, so the model and
            # the part disagree by construction — but the fix is a one-word
            # answer, and refusing the whole plate to ask for it is the
            # behaviour we removed everywhere else.
            out.append(_row(
                "pocket_corner_radius",
                "Pocket internal corners can be cut",
                WARN,
                "the pocket is drawn with sharp internal corners and no "
                "milling cutter can produce one — the part will come out with "
                f"the radius of whatever tool cuts it, at least "
                f"{_SMALLEST_END_MILL_D / 2:g} mm. State a corner radius, or "
                f"say the pocket is wire EDM'd or cast.",
                "an end mill is round; the corner it leaves is its own radius",
                {"corner_radius": r, "smallest_tool_r": _SMALLEST_END_MILL_D / 2},
            ))
        else:
            if r * 2 < _SMALLEST_END_MILL_D:
                out.append(_row(
                    "pocket_corner_tooling",
                    "Pocket corners use a stock cutter",
                    WARN,
                    f"a {r:g} mm corner needs a {r * 2:g} mm cutter, under the "
                    f"{_SMALLEST_END_MILL_D:g} mm a shop normally keeps. It is "
                    f"machinable and it is slower and dearer than it looks.",
                    f"smallest commonly stocked end mill is "
                    f"{_SMALLEST_END_MILL_D:g} mm diameter",
                    {"corner_radius": r},
                ))
            ratio = depth / r
            if ratio > _POCKET_DEPTH_PER_RADIUS:
                out.append(_row(
                    "pocket_depth_ratio",
                    "Pocket is reachable with standard tooling",
                    WARN,
                    f"{depth:g} mm deep on a {r:g} mm corner is {ratio:.1f} "
                    f"tool diameters of reach; past "
                    f"{_POCKET_DEPTH_PER_RADIUS:g} the cutter is slender "
                    f"enough to deflect and chatter. Open the corners or "
                    f"expect a long-reach holder and a light cut.",
                    "flute length of about four diameters before deflection "
                    "dominates",
                    {"depth": depth, "corner_radius": r, "ratio": round(ratio, 2)},
                ))
    return out


def _hole_rules(process: str, f: dict) -> list[dict]:
    if process != "machined":
        return []
    out = []
    for hole in f.get("holes") or []:
        d, depth = hole.get("d"), hole.get("depth")
        if not d or not depth:
            continue
        ratio = depth / d
        if ratio > _HOLE_DEPTH_PER_DIAMETER:
            out.append(_row(
                f"hole_depth_{hole.get('id', 'hole')}",
                "Holes are drillable in one pass",
                WARN,
                f"{hole.get('id', 'a hole')} is {d:g} mm across and {depth:g} mm "
                f"deep — {ratio:.1f} diameters. Past "
                f"{_HOLE_DEPTH_PER_DIAMETER:g} it needs peck cycles or a gun "
                f"drill, and it will wander.",
                "swarf clearance and drill rigidity fall off past about five "
                "diameters",
                {"d": d, "depth": depth, "ratio": round(ratio, 2)},
            ))
    return out


def _wall_rules(process: str, f: dict) -> list[dict]:
    wall = f.get("min_wall")
    floor = _MIN_WALL.get(process)
    if wall is None or floor is None:
        return []
    if wall >= floor:
        return []
    return [_row(
        "min_wall",
        "Walls are thick enough for the process",
        WARN,
        f"the thinnest wall is {wall:g} mm and {process} holds about "
        f"{floor:g} mm. Thinner than that it distorts, and on a cast part it "
        f"may not fill at all.",
        f"minimum section for {process}",
        {"min_wall": wall, "process_floor": floor},
    )]


def _draft_rules(process: str, f: dict) -> list[dict]:
    if process != "cast":
        return []
    if f.get("draft_deg"):
        return []
    return [_row(
        "draft",
        "Cast faces can leave the mould",
        WARN,
        "no draft is stated on any face. A cast part with vertical walls will "
        "not release from the tool; 1 to 2 degrees is usual, and none of these "
        "families can add it yet.",
        "pattern must withdraw from the mould without dragging",
        {"draft_deg": 0.0},
    )]


def _intent_rules(f: dict, engineering_declared: bool) -> list[dict]:
    """What naming an intent obliges the design to have answered.

    A part is only *called* load-bearing by someone who knows it carries
    something. Saying so and stating no load means nothing can check it, and
    the verdict would otherwise read exactly like a part whose strength was
    proved.
    """
    if f.get("function") != "load_bearing" or engineering_declared:
        return []
    return [_row(
        "duty_stated",
        "A load-bearing part has a load to check",
        WARN,
        "this is called load-bearing and no load, pressure or torque was "
        "stated, so nothing here checked whether it survives. The geometry is "
        "verified; the strength is not.",
        "a strength claim needs a duty; none was given",
        {"function": "load_bearing"},
    )]


def check(design_plan: Optional[dict]) -> list[dict]:
    """Manufacturability rows for the frozen ``manufacturing`` declaration.

    Returns ``[]`` when a design declared nothing, which is every part that
    does not say how it is made.
    """
    decl = (design_plan or {}).get("manufacturing")
    if not isinstance(decl, dict):
        return []
    process = str(decl.get("process") or "").strip().lower()
    features = decl.get("features") or {}
    if not isinstance(features, dict):
        features = {}

    rows: list[dict] = []
    rows += _intent_rules(features, bool((design_plan or {}).get("engineering")))
    if process and process not in PROCESSES:
        # Recorded, not guessed at. Applying the milling rules to a process we
        # have no rules for would be inventing evidence.
        rows.append(_row(
            "process_known",
            "The process has manufacturability rules here",
            WARN,
            f"this part says it is made by {process!r}, and there are no rules "
            f"for that here — so nothing below checked it. Known: "
            f"{', '.join(sorted(PROCESSES))}.",
            "no rule set for this process",
            {"process": process},
        ))
        return rows
    if not process:
        return rows

    rows += _pocket_rules(process, features)
    rows += _hole_rules(process, features)
    rows += _wall_rules(process, features)
    rows += _draft_rules(process, features)
    if not rows:
        rows.append(_row(
            "makeable",
            f"Makeable as a {process} part",
            PASS,
            f"every rule for {process} that applies to this geometry holds.",
            f"{process} rule set",
            {"process": process},
        ))
    return rows
