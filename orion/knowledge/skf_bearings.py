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

from orion.knowledge.contract import (
    ComponentLoader,
    Confidence,
    Interface,
    Provenance,
)
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
from orion.knowledge.source import SKF_BEARINGS_2018, Dataset

#: The inch columns are the anchor. They are the only unambiguous tokens on the
#: line — always ``d.dddd`` — so matching them pins the millimetre value that
#: precedes each one and the parser cannot drift into the load ratings.
_INCH = r"\d+\.\d{3,4}"
_ROW = re.compile(
    r"^(?P<designation>\d{3,5}(?:\s*/\s*\S+)?)\s+"
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
        core = re.match(r"^(\d{3,5})", raw["designation"]).group(1)
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


class DeepGrooveBearingLoader(ComponentLoader):
    """Deep-groove ball bearings, against the generic contract.

    The first family ported. Everything family-specific lives here; the
    pipeline, the gate and the provenance model come from the contract, so the
    next family implements this interface and nothing else.
    """

    family = "rolling_bearing"
    standard = "ISO 15 boundary dimensions"

    def __init__(self, pages: Optional[dict[int, str]] = None) -> None:
        self._pages = pages or {}

    # -- what only this family knows ---------------------------------- #
    def parse_designation(self, text: str) -> Optional[dict]:
        """What a designation encodes, as a checkable claim.

        ``6205`` is series 62 with a 25 mm bore; ``623`` is series 62 with a
        3 mm bore. The miniature series puts its bore in the last SINGLE digit
        and in millimetres directly, which is why reading the last two would
        call 623 a 115 mm bore.
        """
        # LEADING digit run only. Stripping every digit turns "6205-2RS" into
        # "62052" — a five-digit code implying a 260 mm bore — because the 2 in
        # the seal suffix gets absorbed into the designation.
        match = re.match(r"^\s*(\d{3,5})", str(text))
        if not match:
            return None
        core = match.group(1)
        if len(core) == 3:
            return {"designation": core, "series": core[:2],
                    "bore_mm": float(core[-1])}
        code = int(core[-2:])
        bore = {0: 10.0, 1: 12.0, 2: 15.0, 3: 17.0}.get(code, code * 5.0)
        return {"designation": core, "series": core[:-2], "bore_mm": bore}

    def extract(self, document) -> Iterator[dict]:
        for index, text in sorted(self._pages.items()):
            for row in parse_page(text):
                row["source_page"] = index
                yield row

    def invariants(self):
        return INVARIANTS

    def soft_invariants(self):
        return SOFT

    def properties(self, row: dict) -> dict:
        out = {}
        if "C_N" in row:
            out["dynamic_load_rating_N"] = row["C_N"]
            out["static_load_rating_N"] = row["C0_N"]
        return out

    def interfaces(self, row: dict) -> list[Interface]:
        """The three faces a bearing meets a design through.

        These are the graph edges. A shaft seat and a housing seat each carry
        the fit class the duty implies; the abutment is the shoulder the ring
        bears against, and it is deliberately absent here rather than derived,
        because a shoulder that fouls the corner radius fails invisibly.
        """
        return [
            Interface(kind="shaft_seat", nominal_mm=row["d"],
                      fit_class="k5 (rotating inner ring, normal load)",
                      constraint="interference; the ring must not creep"),
            Interface(kind="housing_seat", nominal_mm=row["D"],
                      fit_class="H7 (stationary outer ring load)",
                      constraint="clearance so the ring can take up thermal "
                                 "growth axially"),
            Interface(kind="width", nominal_mm=row["B"],
                      constraint="the seat must take the full ring width"),
        ]

    def confidence(self, row: dict) -> str:
        """Geometry was cross-checked against the inch columns; ratings only
        count as measured when they survived their own N/lbf checksum."""
        return (Confidence.MEASURED if "C_N" in row else Confidence.READ)

    def provenance(self, row: dict) -> Provenance:
        return Provenance(document=SKF_BEARINGS_2018.document,
                          pages=[row["source_page"]] if "source_page" in row
                          else [],
                          standard=self.standard,
                          table="single row deep groove ball bearings")

    def cross_row_checks(self, rows: list[dict]):
        return series_monotonic(
            rows,
            series_of=lambda r: r["designation"][:-2],
            order_of=lambda r: int(r["designation"][-2:]))


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
    dataset = Dataset(
        family="rolling_bearing",
        source=SKF_BEARINGS_2018,
        rows=[{"designation": k, **v} for k, v in by_designation.items()],
        gate={"accepted": len(result.accepted),
              "rejected": len(result.rejected),
              "with_load_ratings": rated,
              "invariants": [
                  "mm/inch columns agree to 0.002 in",
                  "N/lbf load ratings agree to 1%",
                  "designation size code encodes the bore",
                  "bore < outside diameter; all dimensions positive",
                  "dimensions monotonic within a series"]},
        notes=["Geometry is MEASURED: every dimension was cross-checked "
               "against the catalogue's own inch column. Load ratings are "
               "present only where they survived their N/lbf checksum.",
               "Abutment dimensions are NOT here. They are a separate "
               "manufacturer recommendation and could not be attributed to "
               "designations from this document."])
    payload = dataset.to_dict()
    # Kept alongside `rows` so existing consumers keep working while callers
    # migrate to the versioned shape.
    payload["bearings"] = by_designation
    payload["source_pages"] = result.pages[:40]
    write_catalogue(args.out, payload)
    print(f"wrote {len(by_designation)} bearings to {args.out} "
          f"({rated} with load ratings that passed their N/lbf checksum)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
