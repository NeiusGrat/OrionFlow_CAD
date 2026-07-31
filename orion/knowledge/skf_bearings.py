"""Read the SKF catalogue's deep-groove tables, and refuse anything that fails.

The tables print every dimension twice — millimetres and inches — which makes
them self-checking. A parser that drifts by one column produces rows whose inch
value no longer equals the millimetre value over 25.4, and the gate throws them
out. That is what makes automated extraction from a 587-page catalogue safe
enough to trust: the document carries its own checksum, and we use it.

Run::

    python -m orion.knowledge.skf_bearings --pdf "pdf files/<catalogue>.pdf"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Iterator, Optional

from orion.knowledge.ingest import (
    Harvest,
    designation_encodes_bore,
    gate,
    mm_inch_agree,
    ordered,
    positive,
    series_monotonic,
    within,
    write_catalogue,
)

#: The inch columns are the anchor. They are the only unambiguous tokens on the
#: line — always ``d.dddd`` — so matching them pins the millimetre value that
#: precedes each one and the parser cannot drift into the load ratings.
_INCH = r"\d+\.\d{3,4}"
_ROW = re.compile(
    r"^(?P<designation>\d{4,5}(?:\s*/\s*\S+)?)\s+"
    r"(?P<d>[\d.]+)\s+(?P<d_in>%s)\s+"
    r"(?P<D>[\d.]+)\s+(?P<D_in>%s)\s+"
    r"(?P<B>[\d.]+)\s+(?P<B_in>%s)\s+"
    r"(?P<rest>.+)$" % (_INCH, _INCH, _INCH)
)

#: Thousands are spaced in this catalogue ("14 800"), so a number is up to three
#: digits followed by any number of space-separated triples. Anchored on the
#: triple length, which is what stops "25 0.9843" being read as one value.
_SPACED = re.compile(r"\d{1,3}(?: \d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _number(text: str) -> float:
    return float(text.replace(" ", ""))


def parse_page(text: str) -> Iterator[dict]:
    for line in (text or "").splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        raw = match.groupdict()
        # The remainder holds C, C_lbf, C0, C0_lbf, two speeds and two masses.
        # Fewer than four numbers means this is not a full dimension row.
        tail = [_number(t) for t in _SPACED.findall(raw["rest"])]
        if len(tail) < 4:
            continue
        # "6205 / C78" and "6205" are the same envelope; the suffix is a
        # clearance or seal variant and does not change the boundary.
        core = re.match(r"^(\d{4,5})", raw["designation"]).group(1)
        try:
            yield {
                "designation": core,
                "variant": raw["designation"].strip(),
                "d": float(raw["d"]), "d_in": float(raw["d_in"]),
                "D": float(raw["D"]), "D_in": float(raw["D_in"]),
                "B": float(raw["B"]), "B_in": float(raw["B_in"]),
                "C_N": tail[0], "C_lbf": tail[1],
                "C0_N": tail[2], "C0_lbf": tail[3],
            }
        except ValueError:
            continue


#: Newtons to pounds-force. The catalogue prints both, so this is another
#: derivable column and therefore another checksum.
_LBF_PER_N = 0.2248089431


def load_rating_units_agree(tol_pct: float = 1.0):
    def check(row: dict) -> Optional[str]:
        for newtons, pounds in (("C_N", "C_lbf"), ("C0_N", "C0_lbf")):
            n, lbf = row.get(newtons), row.get(pounds)
            if n is None or lbf is None:
                return f"missing {newtons}/{pounds}"
            expected = float(n) * _LBF_PER_N
            if expected and abs(float(lbf) - expected) / expected * 100 > tol_pct:
                return (f"{newtons}={n} implies {pounds}~{expected:.0f} but the "
                        f"table says {lbf} — columns misaligned or a unit error")
        return None
    return check


#: Hard: the geometry. A row failing any of these is not a bearing row.
INVARIANTS = [
    mm_inch_agree("d", "d_in"),
    mm_inch_agree("D", "D_in"),
    mm_inch_agree("B", "B_in"),
    positive("d", "D", "B"),
    ordered("d", "D"),
    designation_encodes_bore(),
    within("d", 1.0, 1200.0),
    within("B", 1.0, 400.0),
]

#: Soft: the load ratings, which sit in columns pypdf sometimes runs together
#: ("25170" and "100000" emerging as one token). Their N/lbf pair is its own
#: checksum, so a merge is detectable — and when it fires the ratings are
#: dropped while the verified dimensions are kept.
SOFT = [(load_rating_units_agree(), ("C_N", "C_lbf", "C0_N", "C0_lbf"))]


def harvest(pdf_path: str, first: int = 0, last: Optional[int] = None) -> Harvest:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    last = min(last or len(reader.pages), len(reader.pages))
    rows: list[dict] = []
    pages: list[int] = []
    for index in range(first, last):
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception:  # noqa: BLE001 — one bad page must not end the run
            continue
        found = list(parse_page(text))
        if found:
            rows.extend(found)
            pages.append(index)

    # Deduplicate by designation, preferring the first sighting. Variants of the
    # same bearing repeat the same envelope across the catalogue.
    seen: dict[str, dict] = {}
    for row in rows:
        seen.setdefault(row["designation"], row)

    result = gate(seen.values(), INVARIANTS, soft=SOFT,
                  source=os.path.basename(pdf_path), pages=pages)
    # Cross-row check, which no per-row invariant can catch.
    # The size code is always the LAST two digits; everything before it is the
    # series. Grouping by the first two collides 16100 with 16056 — different
    # series, and the monotonic check then rejects both as out of order.
    # Iterate to a fixed point. Removing an out-of-order row can expose the
    # next one: 32220 was rejected against 32219, which left 32221 — equally
    # wrong — comparing against a row that was no longer there. One pass is not
    # enough when the check is relative to a neighbour that may itself go.
    while True:
        broken = series_monotonic(
            result.accepted,
            series_of=lambda r: r["designation"][:-2],
            order_of=lambda r: int(r["designation"][-2:]))
        if not broken:
            break
        result.rejected.extend(broken)
        gone = {id(r.row) for r in broken}
        result.accepted = [r for r in result.accepted if id(r) not in gone]
    return result


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--last", type=int, default=None)
    ap.add_argument("--out", default=os.path.join("orion", "knowledge",
                                                  "skf_deep_groove.json"))
    args = ap.parse_args(argv)

    result = harvest(args.pdf, args.first, args.last)
    print(result.report())
    if not result.accepted:
        print("nothing accepted — not writing")
        return 1

    by_designation = {}
    for r in sorted(result.accepted, key=lambda r: r["designation"]):
        entry = {"d": r["d"], "D": r["D"], "B": r["B"]}
        if "C_N" in r:                       # survived its own checksum
            entry["C_N"], entry["C0_N"] = r["C_N"], r["C0_N"]
        by_designation[r["designation"]] = entry
    rated = sum(1 for e in by_designation.values() if "C_N" in e)
    write_catalogue(args.out, {
        "schema_version": 1,
        "source": result.source,
        "source_pages": result.pages[:40],
        "gate": {"accepted": len(result.accepted),
                 "rejected": len(result.rejected),
                 "invariants": [
                     "mm/inch columns agree to 0.002 in",
                     "N/lbf load ratings agree to 1%",
                     "designation code x 5 == bore for codes >= 04",
                     "bore < outside diameter; all dimensions positive",
                     "dimensions monotonic within a series"]},
        "bearings": by_designation,
    })
    print(f"wrote {len(by_designation)} bearings to {args.out} "
          f"({rated} with load ratings that passed their N/lbf checksum)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
