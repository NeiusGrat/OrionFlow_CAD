"""Component specs from a vendor STEP (geometry only) or a datasheet PDF (LLM + guard).

The datasheet guard: every number the model returns must appear in the PDF's
text layer ("31" matches "31.0", "31,0", "31.00"). A number that does not —
usually because it lives only in a drawing image — is kept but listed in
``needs_review``, and the component is never ``verified`` until a user confirms.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..llm import LLM, LLMUnavailable, read_datasheet
from .library import Component

DPI = 200
MAX_PAGES = 6


def spec_from_step(path: str | Path, name: str | None = None, type_: str = "motor") -> Component:
    """Largest hole pattern, its coaxial pilot and the shaft, straight from geometry."""
    from ..features import axis_offset, extract, parallel
    from ..ingest_step import read_assembly

    parts, instances, _ = read_assembly(path)
    shapes = [i.shape for i in instances]
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    comp, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(comp)
    for s in shapes:
        builder.Add(comp, s)
    f = extract(comp)
    c = Component(name or Path(path).stem, type_, source={"kind": "vendor_step", "file": Path(path).name})
    pats = [p for p in f.patterns if p.kind in ("rect", "circle")]
    if pats:
        p = max(pats, key=lambda p: (len(p.holes), p.pcd or np.hypot(p.a, p.b)))
        if p.kind == "rect":
            c.mount = {"pattern": "rect", "a_mm": round(p.a, 3), "b_mm": round(p.b, 3), "hole_count": 4,
                       "thread": None, "hole_dia_mm": round(p.diameter, 3)}
        else:
            c.mount = {"pattern": "circle", "pcd_mm": round(p.pcd, 3), "hole_count": len(p.holes),
                       "thread": None, "hole_dia_mm": round(p.diameter, 3)}
        coax = sorted((b for b in f.bosses if parallel(b.axis, p.axis) and axis_offset(b, p.centroid) < 0.5),
                      key=lambda b: -b.diameter)
        if coax:
            c.pilot_dia_mm = round(coax[0].diameter, 3)
            if len(coax) > 1:
                c.shaft_dia_mm = round(coax[-1].diameter, 3)
    c.aliases = [re.escape(c.name.lower().replace("_", " "))]
    c.verified = bool(c.mount)          # measured, not read
    return c


# ------------------------------------------------------------------ datasheets

def _numbers(text: str) -> set[float]:
    out = set()
    for m in re.finditer(r"(?<![\d.])\d+(?:[.,]\d+)?", text):
        try:
            out.add(round(float(m.group().replace(",", ".")), 3))
        except ValueError:
            pass
    return out


def guard(spec: dict, text: str) -> list[str]:
    """Paths of numeric fields whose value is not in the text layer."""
    seen = _numbers(text)
    bad = []

    def visit(d: dict, prefix: str) -> None:
        for k, v in d.items():
            if k in ("page", "hole_count"):
                continue
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                visit(v, path + ".")
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                if round(float(v), 3) not in seen:
                    bad.append(path)
    visit(spec, "")
    return bad


def read_pdf(path: str | Path, llm: LLM) -> Component:
    import pymupdf

    doc = pymupdf.open(str(path))
    text = "\n".join(f"--- page {i + 1} ---\n" + p.get_text() for i, p in enumerate(doc))
    images = [p.get_pixmap(dpi=DPI).tobytes("png") for p in list(doc)[:MAX_PAGES]]
    try:
        spec = read_datasheet(llm, text, images)
    except LLMUnavailable as e:
        raise LLMUnavailable(f"datasheet {Path(path).name} needs the LLM reader: {e}") from e
    needs = guard(spec, text)
    mount = {k: v for k, v in (spec.get("mount") or {}).items() if v is not None}
    c = Component(
        name=spec.get("name") or Path(path).stem, type=spec.get("type") or "other", mount=mount,
        pilot_dia_mm=spec.get("pilot_dia_mm"), shaft_dia_mm=spec.get("shaft_dia_mm"),
        bore_mm=spec.get("bore_mm"), od_mm=spec.get("od_mm"), width_mm=spec.get("width_mm"),
        mass_kg=spec.get("mass_kg"),
        source={"kind": "datasheet", "file": Path(path).name, "page": spec.get("page")},
        verified=False, needs_review=needs)
    c.aliases = [re.escape(c.name.lower().replace("_", " "))]
    return c
