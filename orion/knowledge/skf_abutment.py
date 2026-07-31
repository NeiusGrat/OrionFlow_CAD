"""Attribute abutment dimensions to the bearings they belong to.

The abutment tables carry no designation. They sit on the right-hand page of a
product spread, row-aligned with the dimensions and designations on the left,
and that alignment is the only thing linking a ``Da max`` to a bearing. Joining
on bore alone cannot work: 6205, 6305 and 6405 all have a 25 mm bore and
different abutment diameters.

So the join is positional, and it is only allowed to stand when physics agrees:

* the shaft abutment must be **larger** than the bore, or the shoulder does not
  reach the inner ring;
* the housing abutment must be **smaller** than the outside diameter, or it
  does not reach the outer ring;
* the fillet must clear the bearing's own corner radius;
* where both pages print ``d``, they must be the same number.

A misalignment by even one row breaks at least one of those, because the rows
are ordered by increasing size. That is what makes a positional join safe
enough to trust — and every attributed row is marked ``attributed`` rather than
``measured``, because it is correct only if the alignment is, and a consumer
that cannot tell the difference will eventually machine to the wrong one.

Anything that cannot be matched uniquely stays unresolved. It is reported, not
dropped, because an abutment dimension nobody can attribute is a gap worth
seeing.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional

from orion.knowledge.contract import Confidence
from orion.knowledge.ingest import Rejection, write_catalogue

#: The designation on a product row. Dimensions are NOT parsed here: a
#: continuation row omits the bore, which makes its first number ambiguous
#: between d and D, and 595 bearings with verified envelopes already exist.
#: The designation is the join key and the catalogue supplies the geometry,
#: so the positional join is checked against dimensions that passed their
#: own mm/inch checksum rather than against a second guess from the same page.
_DESIGNATION = re.compile(r"(\d{3,5})(?:-[0-9A-Z]+)?")

#: An abutment row: an optional leading d, then the ring and abutment columns.
_ABUTMENT = re.compile(r"^\s*(?P<d>\d+(?:,\d+)?)?\s+(?P<rest>[\d,\s?–—-]+)$")
_TOKEN = re.compile(r"\d+(?:,\d+)?|[?–—-]")


def _num(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    text = text.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def known_envelopes() -> dict:
    """The verified catalogue: designation -> d, D, B."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "skf_deep_groove.json")
    try:
        import json
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("bearings", {})
    except (OSError, ValueError):
        return {}


def parse_product_page(text: str, envelopes: dict) -> list[dict]:
    """Designations in page order, with envelopes from the verified catalogue.

    One row per line, taking the FIRST designation: a line may carry an open
    bearing and its capped variants (``623-2RS1  623-RS1``), which are the same
    envelope and the same row.
    """
    rows: list[dict] = []
    for line in (text or "").splitlines():
        for token in _DESIGNATION.findall(line):
            spec = envelopes.get(token)
            if spec is None:
                continue          # not a bearing we have verified geometry for
            rows.append({"designation": token, "d": spec["d"],
                         "D": spec["D"], "B": spec["B"]})
            break                 # first designation on the line wins
    return rows


def parse_abutment_page(text: str) -> list[dict]:
    """Abutment values, in page order.

    Columns are d, d1, d2, D1, D2, r1,2, da min, da min, Da max, ra max, kr,
    f0. Dashes stand for values that do not apply and become None rather than
    shifting everything after them left.
    """
    rows: list[dict] = []
    carried_d: Optional[float] = None
    for line in (text or "").splitlines():
        match = _ABUTMENT.match(line)
        if not match:
            continue
        tokens = _TOKEN.findall(match.group("rest"))
        if len(tokens) < 9:
            continue
        values = [None if t in "?–—-" else _num(t) for t in tokens]
        d = _num(match.group("d"))
        if d is not None:
            carried_d = d
        rows.append({"d_page": d if d is not None else carried_d,
                     "r_min": values[4], "da_min": values[5],
                     "Da_max": values[7], "ra_max": values[8]})
    return rows


# --------------------------------------------------------------------------- #
def attribute(product: list[dict], abutment: list[dict]
              ) -> tuple[list[dict], list[Rejection]]:
    """Join by position, keep only what physics accepts."""
    joined: list[dict] = []
    refused: list[Rejection] = []

    if len(product) != len(abutment):
        # Not an error worth guessing through. Unequal row counts mean the
        # pages are not a matched spread, and any offset would silently pair a
        # bearing with a neighbour's shoulder.
        refused.append(Rejection(
            {"designation": "?"},
            f"the spread has {len(product)} product rows against "
            f"{len(abutment)} abutment rows — not a matched pair, so no "
            f"positional join is defensible"))
        return joined, refused

    for left, right in zip(product, abutment):
        row = {**left, **right, "confidence": Confidence.ATTRIBUTED}
        problem = physics_disagrees(row)
        if problem:
            refused.append(Rejection(row, problem))
            continue
        joined.append(row)
    return joined, refused


def physics_disagrees(row: dict) -> Optional[str]:
    """The checks that make a positional join safe.

    Rows are ordered by increasing size, so an alignment off by one puts a
    small bearing's shoulder against a large bearing's bore. At least one of
    these then fails.
    """
    d, D = row.get("d"), row.get("D")
    da, Da = row.get("da_min"), row.get("Da_max")
    if d is None or D is None:
        return "missing bore or outside diameter"
    if row.get("d_page") is not None and abs(row["d_page"] - d) > 0.01:
        return (f"the abutment page says d={row['d_page']:g} where the product "
                f"page says d={d:g} — the rows are not aligned")
    if da is not None and not d < da < D:
        return (f"shaft abutment {da:g} is not between the bore {d:g} and the "
                f"outside diameter {D:g} — the rows are not aligned")
    if Da is not None and not d < Da < D:
        return (f"housing abutment {Da:g} is not between the bore {d:g} and "
                f"the outside diameter {D:g} — the rows are not aligned")
    if da is not None and Da is not None and da >= Da:
        return (f"shaft abutment {da:g} is not below housing abutment {Da:g}")
    r_min, ra = row.get("r_min"), row.get("ra_max")
    if r_min is not None and ra is not None and ra > r_min:
        return (f"fillet {ra:g} exceeds the bearing corner radius {r_min:g} — "
                f"it would foul the ring")
    return None


def harvest(pdf_path: str, first: int = 0, last: Optional[int] = None):
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    last = min(last or len(reader.pages), len(reader.pages))
    attributed: list[dict] = []
    refused: list[Rejection] = []
    spreads = 0
    envelopes = known_envelopes()

    def page_text(index: int) -> str:
        try:
            return reader.pages[index].extract_text() or ""
        except Exception:  # noqa: BLE001
            return ""

    for index in range(first, last - 1):
        right = page_text(index + 1)
        if "butment" not in right:
            continue
        left = page_text(index)
        product = parse_product_page(left, envelopes)
        abut = parse_abutment_page(right)
        if not product or not abut:
            continue
        spreads += 1
        rows, bad = attribute(product, abut)
        for row in rows:
            row["source_pages"] = [index, index + 1]
        attributed.extend(rows)
        refused.extend(bad)
    return attributed, refused, spreads


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default=os.path.join("orion", "knowledge",
                                                  "skf_abutment.json"))
    args = ap.parse_args(argv)

    rows, refused, spreads = harvest(args.pdf)
    # Unique designations only. A designation appearing twice with different
    # abutment values means the join is not deterministic for it, and an
    # ambiguous row is worse than a missing one.
    counts: dict[str, list[dict]] = {}
    for row in rows:
        counts.setdefault(row["designation"], []).append(row)
    unique, ambiguous = {}, []
    for designation, group in counts.items():
        keys = {(r.get("da_min"), r.get("Da_max"), r.get("ra_max"))
                for r in group}
        if len(keys) == 1:
            r = group[0]
            unique[designation] = {
                "d": r["d"], "D": r["D"], "B": r["B"],
                "da_min": r.get("da_min"), "Da_max": r.get("Da_max"),
                "ra_max": r.get("ra_max"), "r_min": r.get("r_min"),
                "confidence": Confidence.ATTRIBUTED,
                "source_pages": r["source_pages"]}
        else:
            ambiguous.append(designation)

    print(f"{spreads} spreads examined")
    print(f"{len(rows)} rows passed the physics check, "
          f"{len(refused)} refused")
    print(f"{len(unique)} designations attributed uniquely, "
          f"{len(ambiguous)} ambiguous and left unresolved")
    for r in refused[:6]:
        print(f"  REFUSED {r}")
    if not unique:
        print("nothing attributed — not writing")
        return 1

    write_catalogue(args.out, {
        "schema_version": 1,
        "source": os.path.basename(args.pdf),
        "standard": "manufacturer mounting recommendation",
        "units": "mm",
        "confidence": Confidence.ATTRIBUTED,
        "how": "positional join across a product spread, accepted only where "
               "the shaft abutment lies between bore and outside diameter, the "
               "housing abutment likewise, and the fillet clears the bearing "
               "corner radius",
        "gate": {"attributed": len(unique), "refused": len(refused),
                 "ambiguous_left_unresolved": sorted(ambiguous)[:40]},
        "abutments": unique,
    })
    print(f"wrote {len(unique)} attributed rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
