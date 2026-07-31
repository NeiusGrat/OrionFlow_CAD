"""Where a fact came from, precisely enough to re-derive or retire it.

Engineering data goes stale in ways software does not notice. A standard is
revised, a manufacturer changes a recommendation, an edition is superseded — and
a number that was correct in 2018 is quietly wrong afterwards with nothing in
the file to say so. Worse, when a loader is fixed (and every loader here has
been), there is no way to tell which rows predate the fix without a version on
the loader itself.

So every imported row carries its origin down to the page, and every catalogue
carries the loader that produced it. Two consequences worth having: a value can
always be checked against the document it claims to come from, and a loader bug
found later has a precise blast radius.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Source:
    """The document a fact was read from."""

    manufacturer: str = ""
    document: str = ""
    edition: str = ""
    revision_date: str = ""
    standard: str = ""
    #: Semantic version of the loader. Bump the minor when parsing changes in a
    #: way that could alter values, so rows produced before a fix are findable.
    loader: str = ""
    loader_version: str = "1.0"

    def to_dict(self, page: Optional[int] = None) -> dict[str, Any]:
        out = {k: v for k, v in {
            "manufacturer": self.manufacturer, "document": self.document,
            "edition": self.edition, "revision_date": self.revision_date,
            "standard": self.standard, "loader": self.loader,
            "loader_version": self.loader_version}.items() if v}
        if page is not None:
            out["page"] = page
        return out


@dataclass
class Dataset:
    """A catalogue plus everything needed to judge and reproduce it."""

    family: str
    source: Source
    units: str = "mm"
    rows: list[dict] = field(default_factory=list)
    gate: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": 2,
            "family": self.family,
            "units": self.units,
            "source": self.source.to_dict(),
            "gate": self.gate,
            "notes": self.notes,
            "rows": self.rows,
        }


#: The documents ingested so far. Held in one place so an edition change is a
#: single edit rather than a search.
SKF_ROLLING_BEARINGS = Source(
    manufacturer="SKF", document="Rolling Bearings",
    edition="17000/1 EN", revision_date="2018",
    standard="ISO 15 boundary dimensions; ISO 286 seat tolerances",
    loader="orion.knowledge.skf_bearings", loader_version="1.2")

SKF_BEARINGS_2018 = Source(
    manufacturer="SKF", document="SKF bearings and mounted products",
    edition="100-700 (2018)", revision_date="2018",
    standard="ISO 15 boundary dimensions",
    loader="orion.knowledge.skf_bearings", loader_version="1.2")

PARKER_ORING_HANDBOOK = Source(
    manufacturer="Parker Hannifin", document="O-Ring Handbook",
    edition="PTD5705-EN", revision_date="2023",
    standard="manufacturer design recommendation",
    loader="orion.knowledge.parker_orings", loader_version="1.1")
