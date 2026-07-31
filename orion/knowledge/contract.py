"""The contract every component family implements.

Two families in and the shape was already repeating: find the tables, pull rows,
normalise units, gate on invariants, write a catalogue. The third family should
not re-derive that. This states the pipeline once —

    document -> extract -> normalise -> gate -> relate -> catalogue

— and asks a loader for the seven things only it can know:

* **designation grammar** — how an identifier is spelled, and what it encodes.
  ``6205`` says series 62 and a 25 mm bore; that is a checkable claim, not a
  label.
* **geometry** — the dimensions, per row.
* **properties** — engineering values that are not geometry: load ratings,
  speed limits, pressure ranges.
* **interfaces** — what the part mates with and under what constraint. These
  are the edges of the knowledge graph; a bearing exposes a shaft seat, a
  housing seat and an abutment face, and a groove exposes a bore with a squeeze
  band. Components are nodes, interfaces are why they connect.
* **invariants** — the properties the data must have for structural reasons.
* **provenance** — the document and page every fact came from.
* **confidence** — how the row was established. A value read from one column is
  not the same as one inferred by aligning two tables, and a consumer that
  cannot tell them apart will eventually machine to the wrong one.

The pipeline is deliberately dull. Everything interesting about a family lives
in its loader, and everything that keeps the data honest lives in the gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Optional

from orion.knowledge.ingest import Harvest, Invariant, gate


class Confidence:
    """How a row came to be, worst to best.

    Not a probability. These are kinds of evidence, and the distinction that
    matters is whether a human would have to check it before machining to it.
    """

    #: Read directly from a column, and cross-checked against another column
    #: in the same table (mm against inches, N against lbf).
    MEASURED = "measured"
    #: Read directly, with no independent column to check it against.
    READ = "read"
    #: Established by joining two tables — correct only if the join is correct,
    #: even when every individual value was read cleanly.
    ATTRIBUTED = "attributed"
    #: Computed from other values by a rule, e.g. a shoulder backed off from a
    #: corner radius. Correct only if the rule applies to this case.
    DERIVED = "derived"

    ORDER = (DERIVED, ATTRIBUTED, READ, MEASURED)

    @classmethod
    def weakest(cls, *levels: str) -> str:
        """A row is only as trustworthy as its least certain ingredient."""
        present = [x for x in levels if x in cls.ORDER]
        return min(present, key=cls.ORDER.index) if present else cls.DERIVED


@dataclass
class Interface:
    """One way a component meets another. An edge of the knowledge graph."""

    kind: str                       # "shaft_seat", "housing_seat", "abutment"
    nominal_mm: Optional[float] = None
    fit_class: str = ""             # ISO 286 class where one applies
    constraint: str = ""            # what must hold for the mate to be correct
    note: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "kind": self.kind, "nominal_mm": self.nominal_mm,
            "fit_class": self.fit_class, "constraint": self.constraint,
            "note": self.note}.items() if v not in ("", None)}


@dataclass
class Provenance:
    document: str = ""
    pages: list[int] = field(default_factory=list)
    standard: str = ""
    table: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "document": self.document, "pages": self.pages,
            "standard": self.standard, "table": self.table}.items() if v}


class ComponentLoader(ABC):
    """What a family must supply. Everything else is the pipeline's job."""

    #: Stable family name, e.g. "deep_groove_ball_bearing".
    family: str = ""
    #: The standard the boundary dimensions come from, where there is one.
    standard: str = ""

    @abstractmethod
    def extract(self, document: Any) -> Iterator[dict]:
        """Rows straight off the document, before any checking."""

    @abstractmethod
    def invariants(self) -> list[Invariant]:
        """Hard checks. A row failing any of these does not enter."""

    def soft_invariants(self) -> list[tuple[Invariant, tuple[str, ...]]]:
        """Checks that drop a field group instead of the row.

        Facts in a table are independent: geometry that passed its own checksum
        is still good when an unrelated column extracted badly.
        """
        return []

    def parse_designation(self, text: str) -> Optional[dict]:
        """What the identifier encodes, or None if it is not one of ours."""
        return None

    def properties(self, row: dict) -> dict:
        """Engineering values that are not geometry."""
        return {}

    def interfaces(self, row: dict) -> list[Interface]:
        """How this component meets others. The graph edges."""
        return []

    def confidence(self, row: dict) -> str:
        return row.get("confidence", Confidence.READ)

    def provenance(self, row: dict) -> Provenance:
        return Provenance(pages=[row["source_page"]] if "source_page" in row
                          else [], standard=self.standard)

    def cross_row_checks(self, rows: list[dict]) -> list:
        """Checks needing the whole set, e.g. monotonicity within a series."""
        return []


def run(loader: ComponentLoader, document: Any, source: str = "") -> Harvest:
    """document -> extract -> gate -> relate. The dull part, written once."""
    rows = list(loader.extract(document))
    result = gate(rows, loader.invariants(), soft=loader.soft_invariants(),
                  source=source)

    # Cross-row checks iterate: removing an out-of-order row can expose the
    # next one, and a single pass leaves the second offender in place.
    while True:
        broken = loader.cross_row_checks(result.accepted)
        if not broken:
            break
        result.rejected.extend(broken)
        gone = {id(r.row) for r in broken}
        result.accepted = [r for r in result.accepted if id(r) not in gone]

    for row in result.accepted:
        row["family"] = loader.family
        row["confidence"] = loader.confidence(row)
        row["provenance"] = loader.provenance(row).to_dict()
        props = loader.properties(row)
        if props:
            row["properties"] = props
        edges = [i.to_dict() for i in loader.interfaces(row)]
        if edges:
            row["interfaces"] = edges
    return result


def summarise(result: Harvest) -> dict:
    """Counts by confidence, so a catalogue says how well it is known."""
    by_confidence: dict[str, int] = {}
    for row in result.accepted:
        level = row.get("confidence", Confidence.READ)
        by_confidence[level] = by_confidence.get(level, 0) + 1
    return {"accepted": len(result.accepted),
            "rejected": len(result.rejected),
            "by_confidence": dict(sorted(by_confidence.items()))}


def unresolved(rows: Iterable[dict], reason_key: str = "unresolved") -> list[dict]:
    """Rows kept but not attributed — visible rather than dropped."""
    return [r for r in rows if r.get(reason_key)]
