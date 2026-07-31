"""ISO 286 seat deviations, from SKF's own fit tables.

This is the table that was missing. Without it only one bearing duty could be
resolved — a stationary outer ring in a housing it may slide in — because a fit
class with no numbers behind it is a class you cannot machine to. Every press
fit, every rotating-outer-ring arrangement and every shaft seat needed this.

I refused to take it from a web page earlier: an extraction there disagreed with
the canonical IT7 series on two of five rows, and a fit table that is subtly
wrong produces a housing that assembles wrongly with nothing to indicate it. The
catalogue settles it — its H7 column reads 0/+21, 0/+25, 0/+30 across 18-30,
30-50 and 50-80 mm, which is IT7 exactly and which the web extraction did not.

The invariants here are unusually strong, because ISO 286 defines these classes
structurally rather than empirically:

* an **H** class has a lower deviation of exactly zero, by definition of the
  letter — the hole is never smaller than nominal;
* an H class's upper deviation **is** the IT grade named by its digit, so H7 at
  30-50 mm must be +25 um and nothing else. That is a derivable column checked
  against a table we already had, which means the two validate each other;
* deviations are ordered (lower below upper) and ranges are contiguous.

Run::

    python -m orion.knowledge.skf_fits --pdf "pdf files/<catalogue>.pdf"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Iterator, Optional

from orion.knowledge.ingest import Harvest, gate, write_catalogue

#: ISO 286 standard tolerance grades, micrometres, by nominal size band. Held
#: here so the H-class deviations parsed out of the catalogue can be checked
#: against a number that did not come from the same page.
IT_GRADES = {
    6: [(3, 6, 8), (6, 10, 9), (10, 18, 11), (18, 30, 13), (30, 50, 16),
        (50, 80, 19), (80, 120, 22), (120, 180, 25), (180, 250, 29)],
    7: [(3, 6, 12), (6, 10, 15), (10, 18, 18), (18, 30, 21), (30, 50, 25),
        (50, 80, 30), (80, 120, 35), (120, 180, 40), (180, 250, 46)],
    8: [(3, 6, 18), (6, 10, 22), (10, 18, 27), (18, 30, 33), (30, 50, 39),
        (50, 80, 46), (80, 120, 54), (120, 180, 63), (180, 250, 72)],
    9: [(3, 6, 30), (6, 10, 36), (10, 18, 43), (18, 30, 52), (30, 50, 62),
        (50, 80, 74), (80, 120, 87), (120, 180, 100), (180, 250, 115)],
    10: [(3, 6, 48), (6, 10, 58), (10, 18, 70), (18, 30, 84), (30, 50, 100),
         (50, 80, 120), (80, 120, 140), (120, 180, 160), (180, 250, 185)],
}

#: The header naming the classes carried by the columns of a table, e.g.
#: "Dmp H7 H8 H9 H10 J6" or "dmp k5 k6 m5 m6 n5".
_CLASS = re.compile(r"\b([A-Za-z]{1,2}\d)\b")
#: A deviation row: two range bounds, then signed micrometre values.
_ROW = re.compile(r"^(\d+)\s+(\d+)\s+(.+)$")
_SIGNED = re.compile(r"[+−–—-]?\s?\d+(?:,\d+)?")


def it_value(grade: int, lo: float, hi: float) -> Optional[int]:
    for band_lo, band_hi, value in IT_GRADES.get(grade, []):
        if band_lo == lo and band_hi == hi:
            return value
    return None


def _num(token: str) -> float:
    """SKF prints minus as U+2212 and decimals with a comma."""
    text = (token.replace("−", "-").replace("–", "-")
            .replace("—", "-").replace(",", ".").replace(" ", ""))
    return float(text)


def parse_page(text: str, kind: str) -> Iterator[dict]:
    """Yield one row per (size band, tolerance class) on a fit-table page.

    Only the FIRST line of each three-line group is read. The two beneath it are
    theoretical and probable interference — consequences of the deviation, not
    the deviation — and treating them as data would triple every entry with
    numbers that are not tolerances.
    """
    lines = [ln.strip() for ln in (text or "").splitlines()]
    classes = [c for c in _CLASS.findall(" ".join(lines[:16]))
               if re.match(r"^[GHJKMNPghjkmnp]s?\d$", c)]
    if not classes:
        return
    seen_band: set[tuple[float, float]] = set()
    for line in lines:
        match = _ROW.match(line)
        if not match:
            continue
        lo, hi = float(match.group(1)), float(match.group(2))
        if hi <= lo or (lo, hi) in seen_band:
            continue                       # the 2nd/3rd lines repeat no band
        tokens = _SIGNED.findall(match.group(3))
        # The first pair is the BEARING's own tolerance, not a seat class.
        values = [_num(t) for t in tokens][2:]
        if len(values) < 2 * len(classes):
            continue
        seen_band.add((lo, hi))
        for index, cls in enumerate(classes):
            low, high = values[2 * index], values[2 * index + 1]
            yield {"kind": kind, "iso_class": cls,
                   "over_mm": lo, "incl_mm": hi,
                   "lower_um": min(low, high), "upper_um": max(low, high)}


def h_class_lower_is_zero():
    """By definition of the letter H the hole is never smaller than nominal."""
    def check(row: dict) -> Optional[str]:
        if row["iso_class"].startswith("H") and row["lower_um"] != 0:
            return (f"{row['iso_class']} has lower deviation "
                    f"{row['lower_um']}, but an H class is zero by definition "
                    f"— the columns are misaligned")
        return None
    return check


def h_class_upper_is_its_it_grade(tol: float = 0.5):
    """H7's upper deviation IS IT7. Checked against a table from elsewhere, so
    the two sources validate each other rather than agreeing by construction."""
    def check(row: dict) -> Optional[str]:
        cls = row["iso_class"]
        if not cls.startswith("H"):
            return None
        expected = it_value(int(cls[1:]), row["over_mm"], row["incl_mm"])
        if expected is None:
            return None                    # band not tabulated here
        if abs(row["upper_um"] - expected) > tol:
            return (f"{cls} at {row['over_mm']:g}-{row['incl_mm']:g} mm should "
                    f"be +{expected} um (IT{cls[1:]}) but the row says "
                    f"{row['upper_um']:+g}")
        return None
    return check


def deviations_ordered():
    def check(row: dict) -> Optional[str]:
        if row["lower_um"] > row["upper_um"]:
            return f"lower {row['lower_um']} above upper {row['upper_um']}"
        if abs(row["upper_um"] - row["lower_um"]) > 400:
            return (f"a {row['upper_um'] - row['lower_um']:g} um band is far "
                    f"too wide for a seat tolerance")
        return None
    return check


def band_is_a_size_step():
    """ISO 286 bands are narrow steps, not spans.

    Real bands go 6-10, 18-30, 400-500 — each at most a small multiple of its
    lower bound. A row reading "1 to 250" is a summary line or a footnote that
    happened to start with two numbers, and because it matches every diameter
    it shadows the correct band for its class.
    """
    def check(row: dict) -> Optional[str]:
        over, incl = row["over_mm"], row["incl_mm"]
        if incl - over > 2 * over + 5:
            return (f"a {over:g}-{incl:g} mm band is a span, not a size step — "
                    f"this is a summary row, and it would shadow every real "
                    f"band for {row['iso_class']}")
        return None
    return check


INVARIANTS = [h_class_lower_is_zero(), h_class_upper_is_its_it_grade(),
              deviations_ordered(), band_is_a_size_step()]


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
        low = text.lower()
        if "housing tolerances" in low:
            kind = "housing"
        elif "shaft tolerances" in low:
            kind = "shaft"
        else:
            continue
        found = list(parse_page(text, kind))
        if found:
            rows.extend(found)
            pages.append(index)

    seen: dict[tuple, dict] = {}
    for row in rows:
        seen.setdefault((row["kind"], row["iso_class"],
                         row["over_mm"], row["incl_mm"]), row)
    return gate(sorted(seen.values(),
                       key=lambda r: (r["kind"], r["iso_class"], r["over_mm"])),
                INVARIANTS, source=os.path.basename(pdf_path), pages=pages)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default=os.path.join("orion", "knowledge",
                                                  "iso286_seat_fits.json"))
    args = ap.parse_args(argv)

    result = harvest(args.pdf)
    print(result.report())
    if not result.accepted:
        print("nothing accepted — not writing")
        return 1

    grouped: dict[str, dict[str, list]] = {}
    for row in result.accepted:
        band = grouped.setdefault(row["kind"], {}).setdefault(row["iso_class"], [])
        band.append([row["over_mm"], row["incl_mm"],
                     row["lower_um"], row["upper_um"]])
    for kind in grouped:
        for cls in grouped[kind]:
            grouped[kind][cls].sort()

    write_catalogue(args.out, {
        "schema_version": 1,
        "source": result.source,
        "source_pages": result.pages,
        "units": "micrometres; [over_mm, incl_mm, lower_um, upper_um]",
        "gate": {"accepted": len(result.accepted),
                 "rejected": len(result.rejected),
                 "invariants": [
                     "H classes have a lower deviation of exactly zero",
                     "an H class's upper deviation equals its IT grade, "
                     "checked against an independently held IT table",
                     "lower below upper; band width physically plausible"]},
        "fits": grouped,
    })
    counts = {k: {c: len(v) for c, v in sorted(g.items())}
              for k, g in sorted(grouped.items())}
    print(f"wrote {args.out}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
