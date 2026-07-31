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

from orion.knowledge.ingest import Harvest, gate, ordered, positive, write_catalogue

#: "1.78 ±0.08 1.45 0.16 - 0.45  9 - 25 2.40 - 2.60 3.50 - 3.70 4.60 - 4.80 ..."
_RANGE = r"([\d.]+)\s*-\s*([\d.]+)"
_ROW = re.compile(
    r"^(?P<d2>\d+\.\d+)\s*[^\d]{0,3}(?P<d2_tol>\d+\.\d+)\s+"
    r"(?P<t>\d+\.\d+)\s+"
    r"%s\s+%s\s+%s\s+%s\s+%s" % (_RANGE, _RANGE, _RANGE, _RANGE, _RANGE)
)


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


def harvest(pdf_path: str) -> Harvest:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    rows: list[dict] = []
    pages: list[int] = []
    for index in range(len(reader.pages)):
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception:  # noqa: BLE001
            continue
        found = list(parse_page(text))
        if found:
            for row in found:
                row["source_page"] = index
            rows.extend(found)
            pages.append(index)

    # The handbook carries several gland tables — piston, rod, face seal,
    # static, dynamic — and they give DIFFERENT depths for the same cord. The
    # page is therefore part of a row's identity, not decoration: deduplicating
    # on cord diameter alone silently mixes applications, and a face-seal gland
    # used on a piston is a seal that fails.
    seen: dict[tuple, dict] = {}
    for row in rows:
        seen.setdefault((row["source_page"], row["cord_dia_mm"]), row)
    return gate(sorted(seen.values(),
                       key=lambda r: (r["source_page"], r["cord_dia_mm"])),
                INVARIANTS, source=os.path.basename(pdf_path), pages=pages)


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

    write_catalogue(args.out, {
        "schema_version": 1,
        "source": result.source,
        "source_pages": result.pages[:20],
        # NOT claimed as a single application. The handbook has separate gland
        # tables per sealing arrangement and this parser does not read the
        # heading above each one, so every row carries the page it came from and
        # the caller must confirm the application before machining a groove.
        "applies_to": "UNRESOLVED — each row carries source_page; confirm the "
                      "sealing arrangement against that page of the handbook "
                      "before use",
        "gate": {"accepted": len(result.accepted),
                 "rejected": len(result.rejected),
                 "invariants": [
                     "gland depth < cord diameter (squeeze exists)",
                     "groove widths increase with anti-extrusion rings",
                     "compression and width ranges ordered",
                     "stated compression % within 4 points of mm/cord"]},
        "glands": result.accepted,
    })
    print(f"wrote {len(result.accepted)} gland rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
