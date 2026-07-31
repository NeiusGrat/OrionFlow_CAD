"""Read Parker's O-ring gland tables under the invariant gate.

An O-ring groove is a feature we can cut, and getting it wrong has a failure
mode that never shows in the model: too little squeeze and the seal leaks, too
much and it takes a compression set and leaks later. The numbers are not
guessable and they are not derivable from the cord diameter alone, which makes
this exactly the kind of thing a skill should own.

Unlike the SKF tables this one is metric-only, so there is no mm/inch checksum.
What it does have is a set of structural relationships strong enough to catch a
drifting parser:

* the gland is shallower than the cord — otherwise there is no squeeze at all;
* the groove widens with each anti-extrusion ring, so b1 < b2 < b3;
* the compression range is ordered, and the stated percentage lands within a
  few points of compression over cord diameter. That last one is a *band* check
  rather than an equality, because the published percentage carries a tolerance
  stack this parser cannot reconstruct — a weaker invariant, and labelled as
  one, but still enough to catch a column shift, which throws the value out by
  an order of magnitude rather than by a point.

Run::

    python -m orion.knowledge.parker_orings --pdf "pdf files/<handbook>.pdf"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Iterator, Optional

from orion.knowledge.contract import (
    ComponentLoader,
    Confidence,
    Interface,
    Provenance,
    run,
)
from orion.knowledge.ingest import Harvest, ordered, positive, write_catalogue
from orion.knowledge.source import PARKER_ORING_HANDBOOK, Dataset

#: "1.78 ±0.08 1.45 0.16 - 0.45  9 - 25 2.40 - 2.60 3.50 - 3.70 4.60 - 4.80 ..."
_RANGE = r"([\d.]+)\s*-\s*([\d.]+)"
_ROW = re.compile(
    r"^(?P<d2>\d+\.\d+)\s*[^\d]{0,3}(?P<d2_tol>\d+\.\d+)\s+"
    r"(?P<t>\d+\.\d+)\s+"
    r"%s\s+%s\s+%s\s+%s\s+%s" % (_RANGE, _RANGE, _RANGE, _RANGE, _RANGE)
)


#: What the page says about the sealing arrangement. Section 3.1 is static,
#: 3.2 dynamic; the figure captions name the arrangement. A gland table inherits
#: whichever context its page states.
_MOTION = (("dynamic sealing", "dynamic"), ("static sealing", "static"))
_ARRANGEMENT = (("piston seal", "piston"), ("rod seal", "rod"),
                ("flange seal", "face"), ("axial compression", "face"))
_MEDIUM = (("hydraulic", "hydraulic"), ("pneumatic", "pneumatic"))


def resolve_application(text: str) -> dict:
    """Which sealing arrangement a page's gland table applies to.

    Returns every arrangement the page names rather than picking one. A page
    that discusses piston, rod and flange seals together may carry a table for
    all three or for one of them, and this parser cannot tell which — so it says
    so instead of choosing. A face-seal gland used on a piston is a seal that
    fails, and the failure is invisible in the model.
    """
    low = (text or "").lower()
    motion = next((v for k, v in _MOTION if k in low), "")
    arrangements = sorted({v for k, v in _ARRANGEMENT if k in low})
    medium = next((v for k, v in _MEDIUM if k in low), "")
    resolved = len(arrangements) == 1 and bool(motion)
    return {
        "motion": motion,
        "arrangements": arrangements,
        "medium": medium,
        "applies_to": (f"{motion}_{arrangements[0]}" if resolved
                       else "AMBIGUOUS"),
        "resolved": resolved,
    }


def parse_page(text: str) -> Iterator[dict]:
    for line in (text or "").splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        g = match.groups()
        try:
            yield {
                "cord_dia_mm": float(match.group("d2")),
                "cord_tol_mm": float(match.group("d2_tol")),
                "gland_depth_mm": float(match.group("t")),
                "compression_min_mm": float(g[3]), "compression_max_mm": float(g[4]),
                "compression_min_pct": float(g[5]), "compression_max_pct": float(g[6]),
                "groove_width_b1_min": float(g[7]), "groove_width_b1_max": float(g[8]),
                "groove_width_b2_min": float(g[9]), "groove_width_b2_max": float(g[10]),
                "groove_width_b3_min": float(g[11]), "groove_width_b3_max": float(g[12]),
            }
        except (ValueError, IndexError):
            continue


def squeeze_exists():
    """The gland must be shallower than the cord or nothing is squeezed."""
    def check(row: dict) -> Optional[str]:
        d2, t = row.get("cord_dia_mm"), row.get("gland_depth_mm")
        if d2 is None or t is None:
            return "missing cord diameter or gland depth"
        if t >= d2:
            return (f"gland depth {t} is not less than cord {d2} — there would "
                    f"be no squeeze, so the columns are misaligned")
        return None
    return check


def widths_increase_with_backup_rings():
    """Each anti-extrusion ring widens the groove; b1 < b2 < b3."""
    def check(row: dict) -> Optional[str]:
        b1, b2, b3 = (row.get("groove_width_b1_min"),
                      row.get("groove_width_b2_min"),
                      row.get("groove_width_b3_min"))
        if None in (b1, b2, b3):
            return "missing a groove width"
        if not b1 < b2 < b3:
            return (f"groove widths {b1}/{b2}/{b3} do not increase with backup "
                    f"rings — the columns are misaligned")
        return None
    return check


def compression_percent_is_plausible(points: float = 4.0):
    """A band check, not an equality.

    The published percentage carries a tolerance stack this parser cannot
    reconstruct — nominal-basis arithmetic reproduces some rows and not others.
    So this only asserts the value is in the right neighbourhood, which is all
    that is needed to catch a shifted column: those land an order of magnitude
    out, not four points.
    """
    def check(row: dict) -> Optional[str]:
        d2 = row.get("cord_dia_mm")
        for mm_key, pct_key in (("compression_min_mm", "compression_min_pct"),
                                ("compression_max_mm", "compression_max_pct")):
            mm, pct = row.get(mm_key), row.get(pct_key)
            if None in (d2, mm, pct):
                return f"missing {mm_key}/{pct_key}"
            implied = mm / d2 * 100.0
            if abs(implied - pct) > points:
                return (f"{mm_key}={mm} on a {d2} cord implies ~{implied:.0f}% "
                        f"but the table says {pct}% — columns misaligned")
        return None
    return check


INVARIANTS = [
    positive("cord_dia_mm", "gland_depth_mm", "compression_min_mm"),
    squeeze_exists(),
    widths_increase_with_backup_rings(),
    ordered("compression_min_mm", "compression_max_mm"),
    ordered("compression_min_pct", "compression_max_pct"),
    ordered("groove_width_b1_min", "groove_width_b1_max"),
    compression_percent_is_plausible(),
]


class ORingGlandLoader(ComponentLoader):
    """O-ring glands, against the generic contract. The second family through
    it, and the one that decides whether the interface generalises.

    Two places it pushed back, both worth recording:

    * an O-ring gland has **no designation**. Its identity is the cord diameter
      *and* the sealing arrangement together, which is why
      ``parse_designation`` returns None here and the contract must not assume
      every family has one. A component identified by its dimensions is
      ordinary — retaining rings and keys are the same.
    * the arrangement is established per *page*, not per row, so extraction has
      to carry page context down into each row. The contract handles this only
      because ``extract`` is free to yield whatever the family needs; a stricter
      signature taking one row at a time could not have.
    """

    family = "o_ring_gland"
    standard = PARKER_ORING_HANDBOOK.standard

    def __init__(self, pages: Optional[dict[int, str]] = None) -> None:
        self._pages = pages or {}

    def extract(self, document) -> Iterator[dict]:
        for index, text in sorted(self._pages.items()):
            application = resolve_application(text)
            for row in parse_page(text):
                row["source_page"] = index
                row.update(application)
                row["standard"] = self.standard
                row["units"] = "mm"
                yield row

    def invariants(self):
        return INVARIANTS

    def parse_designation(self, text: str) -> Optional[dict]:
        """None: a gland has no designation.

        Its identity is (cord diameter, arrangement). Returning a fabricated
        one would let a caller look glands up by a key that does not exist.
        """
        return None

    def properties(self, row: dict) -> dict:
        return {"compression_mm": [row["compression_min_mm"],
                                   row["compression_max_mm"]],
                "compression_pct": [row["compression_min_pct"],
                                    row["compression_max_pct"]]}

    def interfaces(self, row: dict) -> list[Interface]:
        """A groove meets the cord, and the counterface it seals against.

        The squeeze band IS the constraint: outside it the seal either leaks or
        takes a compression set and leaks later, and neither shows in the
        model.
        """
        return [
            Interface(kind="groove_width", nominal_mm=row["groove_width_b1_min"],
                      constraint=f"{row['groove_width_b1_min']:g}.."
                                 f"{row['groove_width_b1_max']:g} mm, no "
                                 f"anti-extrusion ring"),
            Interface(kind="groove_depth", nominal_mm=row["gland_depth_mm"],
                      constraint=f"squeezes a {row['cord_dia_mm']:g} mm cord by "
                                 f"{row['compression_min_pct']:g}-"
                                 f"{row['compression_max_pct']:g}%"),
            Interface(kind="cord", nominal_mm=row["cord_dia_mm"],
                      constraint=f"applies to: {row['applies_to']}"),
        ]

    def confidence(self, row: dict) -> str:
        # An unresolved arrangement means the numbers are right and what they
        # apply to is not — and that is the part a caller would machine to.
        return Confidence.READ if row.get("resolved") else Confidence.DERIVED

    def provenance(self, row: dict) -> Provenance:
        return Provenance(document=PARKER_ORING_HANDBOOK.document,
                          pages=[row["source_page"]],
                          standard=self.standard,
                          table=f"gland dimensions ({row['applies_to']})")


def harvest(pdf_path: str) -> Harvest:
    """Read the document, then hand it to the contract.

    Deduplication happens before the gate because the page is part of a row's
    identity: the handbook gives different depths for the same cord depending
    on the arrangement, and collapsing on cord alone mixes a face seal with a
    piston seal.
    """
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages: dict[int, str] = {}
    for index in range(len(reader.pages)):
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception:  # noqa: BLE001
            continue
        if any(_ROW.match(ln.strip()) for ln in text.splitlines()):
            pages[index] = text

    loader = ORingGlandLoader(pages)
    seen: dict[tuple, dict] = {}
    for row in loader.extract(None):
        seen.setdefault((row["source_page"], row["cord_dia_mm"]), row)

    class _Prepared(ORingGlandLoader):
        def extract(self, document):
            return iter(sorted(seen.values(),
                               key=lambda r: (r["source_page"],
                                              r["cord_dia_mm"])))

    return run(_Prepared(pages), None, source=os.path.basename(pdf_path))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default=os.path.join("orion", "knowledge",
                                                  "parker_oring_glands.json"))
    args = ap.parse_args(argv)

    result = harvest(args.pdf)
    print(result.report())
    if not result.accepted:
        print("nothing accepted — not writing")
        return 1

    by_application: dict[str, list[dict]] = {}
    for row in result.accepted:
        by_application.setdefault(row["applies_to"], []).append(row)

    dataset = Dataset(
        family="o_ring_gland",
        source=PARKER_ORING_HANDBOOK,
        rows=result.accepted,
        gate={"accepted": len(result.accepted),
              "rejected": len(result.rejected),
              "by_application": {k: len(v) for k, v in
                                 sorted(by_application.items())},
              "invariants": [
                  "gland depth < cord diameter (squeeze exists)",
                  "groove widths increase with anti-extrusion rings",
                  "compression and width ranges ordered",
                  "stated compression % within 4 points of mm/cord"]},
        notes=["Rows are keyed by sealing arrangement, never merged: the "
               "handbook gives different gland depths for the same cord "
               "depending on the arrangement, and a face-seal gland used on a "
               "piston is a seal that fails.",
               "AMBIGUOUS means the page named more than one arrangement and "
               "this parser cannot tell which table belongs to which. Those "
               "rows are kept and marked, not guessed at."])
    write_catalogue(args.out, dataset.to_dict())
    print(f"wrote {len(result.accepted)} gland rows to {args.out}")
    for application, group in sorted(by_application.items()):
        print(f"   {application:22s} {len(group)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
