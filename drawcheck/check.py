"""PDF in, report out."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from . import extract_vector, ingest, rules
from .model import Drawing, Report
from .report import fingerprint

if TYPE_CHECKING:
    from .store import Store

#: vision: "off"     never call a vision model
#:         "scanned" only for pages without a text layer (default)
#:         "all"     every page; on vector pages vision output is cross-checked
VISION_MODES = ("off", "scanned", "all")


def read(path: str | Path, vision: str = "scanned", model: str | None = None) -> Drawing:
    if vision not in VISION_MODES:
        raise ValueError(f"vision must be one of {VISION_MODES}")
    d = Drawing(source=str(path), pages=ingest.read_pdf(path))
    extract_vector.extract(d)
    want = [p for p in d.pages if p.scanned] if vision == "scanned" else (d.pages if vision == "all" else [])
    if want:
        from . import extract_vision
        try:
            extract_vision.extract(d, path, [p.index for p in want], model)
        except extract_vision.VisionUnavailable as e:
            d.warnings.append(f"vision reader not run: {e}")
    return d


def check_file(path: str | Path, vision: str = "scanned", store: "Store | None" = None,
               customer: str = "", model: str | None = None) -> tuple[Report, Drawing]:
    d = read(path, vision, model)
    findings = rules.run(d)
    for f in findings:
        f.id = fingerprint(f)
    report = Report(
        source=str(path), pages=len(d.pages), findings=findings,
        title={k: a.text for k, a in d.title.items()},
        reader_warnings=list(d.warnings),
    )
    if store is not None:
        store.apply(report, customer)
    report.stats = {
        "extractors": d.extractors,
        "scanned_pages": [i + 1 for i in d.scanned_pages],
        "annotations": dict(Counter(a.kind for a in d.annotations)),
        "sources": dict(Counter(a.source for a in d.annotations)),
        "untoleranced_dimensions": len(rules._untoleranced(d)),
        "page_layers": [p.layer for p in d.pages],
    }
    if d.vision_stats:
        report.stats["vision"] = d.vision_stats
    return report, d
