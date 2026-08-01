"""Attribute abutment dimensions by constraint satisfaction, never by position.

The abutment tables carry no designation. They sit on their own pages with a
bore heading and a column of ring and shoulder diameters, and the obvious way
to attribute them — walk the rows in order against the designations printed
opposite — is the one thing this module refuses to do. Row order is not
evidence. A single dropped continuation line shifts every subsequent
attribution by one, every value stays plausible, and nothing downstream can
tell. The catalogue itself shows why the order cannot self-check: within the
45 mm bore group ``Da max`` runs 56, 64, 71, **69**, 78, 91 — not monotonic, so
a swapped pair looks exactly like a correct one.

What *is* evidence is geometry. A shoulder either reaches the flat face of a
ring or it fouls the chamfer, and that is decided by numbers we already hold to
a verified standard: every bearing's bore and outside diameter passed a
millimetre/inch checksum at ingest. So attribution is posed as a constraint
satisfaction problem — for each bearing, which abutment rows could physically
belong to it? — and a row is attributed only when the answer is exactly one.

Two or more, and the row is AMBIGUOUS. None, and it is rejected. There is no
third case and no tie-break, because a tie-break is a guess wearing a
justification.

**Confidence never rises above ATTRIBUTED.** The constraints prove a mapping is
physically consistent; they do not prove it is the one the manufacturer
printed. Those are different claims, and a consumer machining a shoulder is
entitled to know which one it has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from orion.knowledge.contract import Confidence

#: Chamfer dimensions from the ISO 15 / ISO 12043 general plans. Used only to
#: recognise which column of a row is the chamfer — not to infer a value.
CHAMFERS = (0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.6, 1.0, 1.1, 1.5, 2.0, 2.1,
            2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 7.5, 9.5)

#: How far the shoulder stands off the ring bore, as a multiple of the chamfer.
#: Measured, not assumed: ``(da min - d) / r`` is computable straight off the
#: abutment page — bore, chamfer and shaft abutment are all in the same row —
#: so this range needed no attribution to establish. Across 959 rows it runs
#: 4.7 to 7.0. The bounds carry a little slack for the catalogue's rounding to
#: 0.1 mm.
K_LO, K_HI = 4.4, 7.3

#: The chamfer removes ``r`` radially from each ring corner, so the flat face
#: a shoulder can actually bear on does not begin until ``2r`` in. This is a
#: geometric floor rather than a fitted one, and it holds for every bearing
#: ever made.
CHAMFER_CLEARANCE = 2.0


@dataclass(frozen=True)
class AbutmentRow:
    """One row of an abutment table, with no idea which bearing it describes."""

    bore: float
    r_min: float
    da_min: float
    Da_max: float
    ra_max: float
    da: Optional[float] = None
    page: int = 0

    def to_dict(self) -> dict:
        return {"bore": self.bore, "r_min": self.r_min, "da_min": self.da_min,
                "da": self.da, "Da_max": self.Da_max, "ra_max": self.ra_max,
                "page": self.page}


# --------------------------------------------------------------------------- #
# the constraints
# --------------------------------------------------------------------------- #
#: Each returns None when it holds, or why it does not. Named, because a
#: mapping that cannot say which constraints proved it is a mapping nobody can
#: audit — and because the ones that did the discriminating are the interesting
#: part of the provenance.
Constraint = Callable[[dict, AbutmentRow], Optional[str]]
CONSTRAINTS: dict[str, Constraint] = {}


def constraint(name: str):
    def register(fn: Constraint) -> Constraint:
        CONSTRAINTS[name] = fn
        return fn
    return register


@constraint("same_bore")
def _same_bore(bearing: dict, row: AbutmentRow) -> Optional[str]:
    if abs(float(bearing["d"]) - row.bore) > 1e-6:
        return f"bore {bearing['d']:g} is not the row's {row.bore:g}"
    return None


@constraint("shaft_shoulder_clears_the_bore")
def _da_over_d(bearing: dict, row: AbutmentRow) -> Optional[str]:
    """A shaft shoulder smaller than the bore does not touch the inner ring."""
    if row.da_min <= float(bearing["d"]):
        return (f"da min {row.da_min:g} does not exceed the bore "
                f"{bearing['d']:g}")
    return None


@constraint("housing_shoulder_inside_the_outside_diameter")
def _Da_under_D(bearing: dict, row: AbutmentRow) -> Optional[str]:
    """A housing shoulder wider than the bearing does not touch the outer ring."""
    if row.Da_max >= float(bearing["D"]):
        return (f"Da max {row.Da_max:g} is not inside the outside diameter "
                f"{bearing['D']:g}")
    return None


@constraint("fillet_fits_inside_the_chamfer")
def _ra_under_r(bearing: dict, row: AbutmentRow) -> Optional[str]:
    """The shoulder's own fillet has to sit within the ring's corner relief."""
    if row.ra_max > row.r_min + 1e-9:
        return (f"fillet ra max {row.ra_max:g} exceeds the chamfer "
                f"{row.r_min:g}")
    return None


@constraint("shaft_shoulder_clears_the_chamfer")
def _shaft_chamfer(bearing: dict, row: AbutmentRow) -> Optional[str]:
    stand_off = row.da_min - float(bearing["d"])
    if stand_off < CHAMFER_CLEARANCE * row.r_min - 1e-9:
        return (f"da min stands off {stand_off:g}, inside the {row.r_min:g} "
                f"chamfer — the shoulder would press on the corner")
    return None


@constraint("housing_shoulder_clears_the_chamfer")
def _housing_chamfer(bearing: dict, row: AbutmentRow) -> Optional[str]:
    stand_off = float(bearing["D"]) - row.Da_max
    if stand_off < CHAMFER_CLEARANCE * row.r_min - 1e-9:
        return (f"Da max stands off {stand_off:g}, inside the {row.r_min:g} "
                f"chamfer — the shoulder would press on the corner")
    return None


@constraint("shaft_stand_off_matches_the_chamfer")
def _shaft_ratio(bearing: dict, row: AbutmentRow) -> Optional[str]:
    """Self-consistency of the row itself, independent of any bearing.

    Catches a misparsed line before it is ever offered to a bearing: if the
    stand-off is not a sane multiple of the chamfer, the columns did not line
    up and the numbers are from two different places.
    """
    if not row.r_min:
        return "no chamfer on the row"
    k = (row.da_min - float(bearing["d"])) / row.r_min
    if not (K_LO <= k <= K_HI):
        return (f"(da min - d)/r = {k:.2f}, outside the {K_LO}..{K_HI} seen "
                f"across the catalogue")
    return None


@constraint("both_shoulders_stand_off_equally")
def _equal_stand_off(bearing: dict, row: AbutmentRow) -> Optional[str]:
    """The discriminating constraint, and it is an equality rather than a band.

    Both shoulders clear the same corner geometry, so they stand off by the
    same amount: ``da min - d`` equals ``D - Da max`` on every row that can be
    checked without attribution. 90x140 stands off 5 and 5; 160x240, 7 and 7;
    8x22, 2 and 2.

    That is far stronger than requiring each side to fall in a range, because
    it *determines* the outside diameter a row belongs to —
    ``D = Da max + (da min - d)`` — instead of merely permitting a span of
    them. A 6209 and a 6309 in the same bore group are then separated by
    millimetres of exact arithmetic rather than by a ratio both happen to
    satisfy.

    The tolerance is for the catalogue's own rounding to 0.1 mm, nothing more.
    """
    shaft = row.da_min - float(bearing["d"])
    housing = float(bearing["D"]) - row.Da_max
    if abs(shaft - housing) > 0.11:
        return (f"the shaft shoulder stands off {shaft:g} but the housing "
                f"shoulder stands off {housing:g}; a row belongs to the "
                f"outside diameter {row.Da_max + shaft:g}, not "
                f"{bearing['D']:g}")
    return None


@constraint("shoulder_supports_the_ring")
def _within_section(bearing: dict, row: AbutmentRow) -> Optional[str]:
    """A shoulder standing off more than half the ring's radial section is
    supporting the ring on nothing."""
    section = (float(bearing["D"]) - float(bearing["d"])) / 2.0
    stand_off = float(bearing["D"]) - row.Da_max
    if stand_off > section:
        return (f"Da max stands off {stand_off:g} of a {section:g} ring "
                f"section — the shoulder misses the ring")
    return None


# --------------------------------------------------------------------------- #
# the join
# --------------------------------------------------------------------------- #
@dataclass
class Match:
    """What the constraints concluded about one bearing."""

    designation: str
    verdict: str                       # attributed | ambiguous | rejected
    row: Optional[AbutmentRow] = None
    satisfied: list[str] = field(default_factory=list)
    candidates: int = 0
    detail: str = ""
    #: Why each rejected row was rejected, kept for the ones that matter.
    near_misses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"designation": self.designation,
                               "verdict": self.verdict,
                               "candidates": self.candidates}
        if self.row:
            out["row"] = self.row.to_dict()
        if self.satisfied:
            out["matching_constraints"] = self.satisfied
        if self.detail:
            out["detail"] = self.detail
        return out


ATTRIBUTED = "attributed"
AMBIGUOUS = "ambiguous"
REJECTED = "rejected"


def candidates_for(bearing: dict, rows: Iterable[AbutmentRow]
                   ) -> tuple[list[AbutmentRow], list[str]]:
    """Every row that could physically belong to this bearing, and why not."""
    keep, why_not = [], []
    for row in rows:
        failures = [f"{name}: {msg}" for name, check in CONSTRAINTS.items()
                    if (msg := check(bearing, row))]
        if failures:
            if len(failures) == 1:          # a near miss is worth reporting
                why_not.append(f"row Da={row.Da_max:g} r={row.r_min:g} — "
                               f"{failures[0]}")
            continue
        keep.append(row)
    return keep, why_not


def attribute(bearing: dict, rows: Iterable[AbutmentRow]) -> Match:
    """Attribute one bearing, or decline to.

    Exactly one physically valid row is an attribution. Anything else is not,
    and no amount of preferring the closest or the first makes it one.
    """
    designation = str(bearing.get("designation", "?"))
    found, near = candidates_for(bearing, rows)

    if not found:
        return Match(designation, REJECTED, candidates=0,
                     detail="no abutment row is physically consistent with "
                            "this bearing", near_misses=near[:3])

    # Rows identical in every attributed value describe the same shoulder, so
    # which one it came from is a distinction without a difference. Collapsing
    # them first stops a duplicated table entry reading as ambiguity.
    distinct = {(r.r_min, r.da_min, r.Da_max, r.ra_max) for r in found}
    if len(distinct) > 1:
        return Match(designation, AMBIGUOUS, candidates=len(distinct),
                     detail="; ".join(
                         f"Da max {r.Da_max:g} with r {r.r_min:g}"
                         for r in found[:4]),
                     near_misses=near[:2])

    return Match(designation, ATTRIBUTED, row=found[0],
                 candidates=1, satisfied=sorted(CONSTRAINTS))


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
_ROW = re.compile(r"^\s*(?P<d>\d{1,4}(?:,\d+)?)?\s+(?P<rest>(?:[\d,]+|[-–—])"
                  r"(?:\s+(?:[\d,]+|[-–—])){6,})\s*$")
_TOKEN = re.compile(r"\d+(?:,\d+)?|[-–—]")


def _num(text: str) -> Optional[float]:
    return None if text in "-–—" else float(text.replace(",", "."))


def parse_pages(pages: Iterable[tuple[int, str]],
                known_bores: set[float]) -> list[AbutmentRow]:
    """Read abutment rows. The bore heading is gated, not trusted.

    A leading token counts as a bore only when it is a bore the verified
    catalogue already contains. Without that check a chamfer value on a
    continuation line reads as the heading of its own group — which produced
    bores of 6.1 and 7.5 mm on the first pass, neither of which exists.

    Note what this is *not*: the bore is a labelled column, so reading it is
    reading the table. Nothing here uses where a row sits.
    """
    out: list[AbutmentRow] = []
    for number, text in pages:
        if "Abutment" not in text or "r1,2" not in text:
            continue
        bore: Optional[float] = None
        for line in text.splitlines():
            match = _ROW.match(line)
            if not match:
                continue
            if match.group("d"):
                candidate = _num(match.group("d"))
                if candidate in known_bores:
                    bore = candidate
            if bore is None:
                continue
            tokens = [_num(t) for t in _TOKEN.findall(match.group("rest"))]
            row = _row_from(tokens, bore, number)
            if row is not None:
                out.append(row)
    return out


def _row_from(tokens: list[Optional[float]], bore: float,
              page: int) -> Optional[AbutmentRow]:
    """Columns are found by what they are, not by where they are.

    The chamfer is the anchor: it is the only column whose value must come from
    a short published set, and the four columns after it are the abutment
    block. A row whose chamfer is not followed by four usable numbers is not an
    abutment row and is dropped rather than half-read.
    """
    for i, value in enumerate(tokens):
        if value not in CHAMFERS or i + 4 >= len(tokens):
            continue
        da_min, da, Da_max, ra_max = tokens[i + 1:i + 5]
        if da_min is None or Da_max is None or ra_max is None:
            continue
        if da_min <= bore or Da_max <= da_min:
            continue
        return AbutmentRow(bore=bore, r_min=value, da_min=da_min, da=da,
                           Da_max=Da_max, ra_max=ra_max, page=page)
    return None


# --------------------------------------------------------------------------- #
def provenance(bearing: dict, match: Match, source: Any) -> dict:
    """The full record for one attributed bearing.

    Deliberately verbose. The values were inferred rather than read against a
    designation, so everything needed to disbelieve them travels with them.
    """
    row = match.row
    return {
        "designation": match.designation,
        "bearing_family": bearing.get("family", "rolling_bearing"),
        "bore": bearing.get("d"),
        "outside_diameter": bearing.get("D"),
        "width": bearing.get("B"),
        "da_min": row.da_min if row else None,
        "Da_max": row.Da_max if row else None,
        "r_min": row.r_min if row else None,
        "ra_max": row.ra_max if row else None,
        "matching_constraints": match.satisfied,
        # Never MEASURED. The constraints prove the mapping is physically
        # consistent, not that it is the one the manufacturer printed.
        "confidence": Confidence.ATTRIBUTED,
        "source_document": getattr(source, "document", ""),
        "source_edition": getattr(source, "edition", ""),
        "source_pages": [row.page] if row else [],
    }


# --------------------------------------------------------------------------- #
def harvest(pdf_path: str, bearings: list[dict], source: Any) -> dict:
    """Run the join over a catalogue and return a dataset ready to write.

    Reports every verdict. The rejected and ambiguous counts are not failures
    of the method — they are the method working. A bearing whose abutment
    cannot be established from geometry alone should keep saying so.
    """
    from collections import defaultdict

    from pypdf import PdfReader

    reader = PdfReader(pdf_path)

    def pages():
        for i, page in enumerate(reader.pages):
            try:
                yield i, (page.extract_text() or "")
            except Exception:                       # noqa: BLE001
                yield i, ""

    bores = {b["d"] for b in bearings if b.get("d")}
    rows = parse_pages(pages(), bores)
    by_bore: dict[float, list[AbutmentRow]] = defaultdict(list)
    for row in rows:
        by_bore[row.bore].append(row)

    attributed, unresolved = {}, []
    counts = {ATTRIBUTED: 0, AMBIGUOUS: 0, REJECTED: 0}
    for bearing in bearings:
        if not (bearing.get("d") and bearing.get("D")):
            continue
        match = attribute(bearing, by_bore.get(bearing["d"], []))
        counts[match.verdict] += 1
        if match.verdict == ATTRIBUTED:
            attributed[match.designation] = provenance(bearing, match, source)
        else:
            unresolved.append({"designation": match.designation,
                               "verdict": match.verdict,
                               "candidates": match.candidates,
                               "detail": match.detail})
    return {"rows_parsed": len(rows), "counts": counts,
            "abutments": attributed, "unresolved": unresolved,
            "constraints": sorted(CONSTRAINTS)}
