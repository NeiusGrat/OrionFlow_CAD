"""What a drawing is made of once it has been read, and what a check found.

Coordinates are PDF points in the page's own frame (origin top-left, y down),
the same frame PyMuPDF reports. A bbox is (x0, y0, x1, y1).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

BBox = tuple[float, float, float, float]

#: Where an annotation came from.
#:   vector     read from the PDF's own text layer: the characters are the
#:              characters the CAD system wrote, nothing was guessed.
#:   vision     read by a vision model from the rendered page.
#:   confirmed  read by the vision model AND matched to vector text at the
#:              same place. Only meaningful on vector pages.
SOURCES = ("vector", "vision", "confirmed")

#: What kind of callout an annotation is.
KINDS = (
    "dimension",       # a size, with or without its own tolerance
    "gdt_frame",       # a feature control frame
    "datum_feature",   # a datum feature symbol (the boxed letter)
    "thread",          # a thread callout
    "surface_finish",  # Ra / Rz / surface texture symbol value
    "note",            # a line of the notes block
    "title_field",     # one labelled field of the title block
    "projection",      # first/third-angle statement or symbol
)


@dataclass
class Word:
    text: str
    bbox: BBox
    font: str = ""
    size: float = 0.0
    dir: tuple[float, float] = (1.0, 0.0)   # writing direction (cos, sin); (1, 0) is horizontal


@dataclass
class Line:
    """Words on one baseline that the PDF wrote as one run of text."""
    text: str
    bbox: BBox
    words: list[Word] = field(default_factory=list)
    font: str = ""


@dataclass
class Page:
    index: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    rects: list[BBox] = field(default_factory=list)   # closed axis-aligned rectangles drawn on the page
    quads: list[list[tuple[float, float]]] = field(default_factory=list)  # closed 4-gons, any rotation
    layer: str = "text"                              # "text" | "outlined" (text drawn as strokes) | "image"
    scanned: bool = False                            # no usable text layer: needs the vision reader
    image_png: bytes | None = field(default=None, repr=False)
    image_scale: float = 1.0                         # image pixels per PDF point


@dataclass
class Annotation:
    kind: str
    text: str
    page: int
    bbox: BBox
    source: str = "vector"
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown annotation kind {self.kind!r}")
        if self.source not in SOURCES:
            raise ValueError(f"unknown annotation source {self.source!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Drawing:
    source: str
    pages: list[Page] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    title: dict[str, Annotation] = field(default_factory=dict)   # field name -> annotation
    extractors: list[str] = field(default_factory=list)          # which readers ran
    warnings: list[str] = field(default_factory=list)            # reader problems, not drawing defects
    vision_pages: list[int] = field(default_factory=list)        # pages the vision reader processed
    vision_stats: dict[str, Any] = field(default_factory=dict)   # tokens, agreement with the text layer

    def of(self, kind: str) -> list[Annotation]:
        return [a for a in self.annotations if a.kind == kind]

    @property
    def scanned_pages(self) -> list[int]:
        return [p.index for p in self.pages if p.scanned]


#: error    the drawing cannot be made or inspected as written: something
#:          required is missing, or two callouts contradict each other.
#: warning  it can be made, but a reasonable shop would have to guess, or a
#:          standard's convention is broken.
#: info     worth raising with the customer, not a defect.
SEVERITIES = ("error", "warning", "info")


@dataclass
class Finding:
    rule: str
    severity: str
    title: str
    message: str
    query: str                          # the question to send back to the customer
    page: int | None = None
    bbox: BBox | None = None
    evidence: str = ""                  # the exact text the finding is about
    standard: str = ""
    clause: str = ""                    # clause number, only when verified
    confidence: str = "vector"          # source of the weakest annotation it rests on
    id: str = ""                        # stable fingerprint, set by the report
    decision: str = ""                  # "", "accepted", "rejected"

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    source: str
    pages: int
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    title: dict[str, str] = field(default_factory=dict)
    reader_warnings: list[str] = field(default_factory=list)
    suppressed: list[Finding] = field(default_factory=list)   # matched an accepted deviation

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "pages": self.pages,
            "title": self.title,
            "stats": self.stats,
            "errors": self.count("error"),
            "warnings": self.count("warning"),
            "infos": self.count("info"),
            "reader_warnings": self.reader_warnings,
            "findings": [f.to_dict() for f in self.findings],
            "suppressed": [f.to_dict() for f in self.suppressed],
        }
