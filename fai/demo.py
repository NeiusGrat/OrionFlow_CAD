"""The three demos, prepared from NIST's public MBE PMI test cases.

    python -m fai.demo prepare [--out data/nist_demo/kit]

Test parts: NIST MBE PMI test cases (https://www.nist.gov/ctl/smart-connected-systems-division/
smart-connected-manufacturing-systems-group/mbe-pmi-0), usable without restriction. Do not use
the NIST logo; credit them as above.

    demo1/   FTC 08 drawing (text drawn as outlines -> needs the vision model) and its AP242 STEP;
             FTC 07 drawing (real text layer -> runs with no model at all) and its AP242 STEP.
             The AP242 file carries semantic PMI, so every run is scored against it.
    demo2/   FTC 07 rev A (as published) and rev B with five PLANTED errors, listed in
             planted_errors.json with where each one is and the rule that must catch it.
    demo3/   FTC 07 box + FTC 08 cover assembled (STEP) and a copy with the cover shifted 1.00 mm.

Every planted change is written down, and the demos say they are planted.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import zipfile
from pathlib import Path

import httpx

NIST = "https://www.nist.gov/document/"
PACKAGES = {"ftc": "nist-ftc-test-case-definitions", "ctc": "nist-ctc-test-case-definitions",
            "pmi": "nist-pmi-step-files"}
FTC = "NIST_MBE_PMI_FTC_Definitions"
PMI = "NIST-PMI-STEP-Files"


def download(raw: Path) -> Path:
    """Fetch and unpack the NIST packages once (about 30 MB)."""
    raw.mkdir(parents=True, exist_ok=True)
    for key, slug in PACKAGES.items():
        dest = raw / slug
        if dest.exists() and any(dest.iterdir()):
            continue
        r = httpx.get(NIST + slug, headers={"User-Agent": "Mozilla/5.0 OrionFlow-Inspect demo kit"},
                      follow_redirects=True, timeout=300)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(dest)
    return raw


# ------------------------------------------------------------------ demo 2: planted errors

def _to_unrotated(page, box):
    import pymupdf

    r = pymupdf.Rect(box) * page.derotation_matrix
    r.normalize()
    return r


def _spans(page):
    """Every text span with its characters and line direction (unrotated coordinates, y down)."""
    for b in page.get_text("rawdict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                s["text"] = "".join(ch["c"] for ch in s["chars"])
                yield s, ln["dir"]


def _quad(s, d, start: int = 0, end: int | None = None):
    """Rotated outline of characters [start:end) of a span, from the PDF's own per-character
    origins and boxes: exact for any font, so neighbours are never clipped."""
    import pymupdf

    chars = s["chars"][start:end]
    chars = [ch for ch in chars if ch["c"].strip()] or chars
    c, sn = d
    size = s["size"]
    along = pymupdf.Point(c, sn)
    up = pymupdf.Point(sn, -c)
    o0 = pymupdf.Point(chars[0]["origin"])
    last = chars[-1]
    lo = pymupdf.Point(last["origin"])
    nxt = s["chars"][end] if end is not None and end < len(s["chars"]) else None
    if nxt is not None:
        # stop just before the next character: a rotated glyph's box overshoots its advance
        o1 = pymupdf.Point(nxt["origin"]) - along * (0.04 * size)
    else:
        lb = pymupdf.Rect(last["bbox"])
        adv = max(((p - lo).x * c + (p - lo).y * sn) for p in (lb.tl, lb.tr, lb.bl, lb.br))
        o1 = lo + along * max(min(adv, 0.75 * size), 0.3 * size)
    p0 = o0 - up * (0.22 * size) - along * (0.08 * size)
    p1 = o1 - up * (0.22 * size)
    p2 = o1 + up * (0.78 * size)
    p3 = o0 + up * (0.78 * size) - along * (0.08 * size)
    return pymupdf.Quad(p3, p2, p0, p1)


def _cover(page, q) -> None:
    """White-out a quad as a six-point polygon: a closed four-sided path around text
    would read as a basic-dimension box to the drawing reader."""
    pts = [q.ul, (q.ul + q.ur) * 0.5, q.ur, q.lr, (q.ll + q.lr) * 0.5, q.ll, q.ul]
    page.draw_polyline(pts, color=None, fill=(1, 1, 1), closePath=True, overlay=True)


def _core(s, d, start: int = 0, end: int | None = None):
    """A thin band through the middle of the targeted characters, so redaction removes them
    and never a neighbour whose rotated box merely overlaps the glyph area."""
    import pymupdf

    chars = s["chars"][start:end]
    c, sn = d
    size = s["size"]
    along = pymupdf.Point(c, sn)
    up = pymupdf.Point(sn, -c)
    o0 = pymupdf.Point(chars[0]["origin"]) + along * (0.1 * size)
    o1 = pymupdf.Point(chars[-1]["origin"]) + along * (0.3 * size)
    return pymupdf.Quad(o0 + up * (0.5 * size), o1 + up * (0.5 * size), o0 + up * (0.2 * size), o1 + up * (0.2 * size))


def _erase(page, s, d, start: int = 0, end: int | None = None) -> None:
    """Remove characters of a span: their text-layer copies and the glyph outlines drawn
    under them (NX exports draw every character as vector strokes too). Line art stays."""
    import pymupdf

    q = _quad(s, d, start, end)
    core = _core(s, d, start, end)          # text removal: only characters centred inside the span
    page.add_redact_annot(core, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    _cover(page, q)


def _write(page, s, d, text: str, start: int = 0) -> None:
    """New text starting at character ``start``'s origin, in the span's direction and colour."""
    import pymupdf

    c, sn = d
    o = pymupdf.Point(s["chars"][start]["origin"])
    # The text layer of these exports is invisible black; the visible glyphs are blue strokes.
    page.insert_text(o, text, fontsize=s["size"], fontname="helv", color=(0.0, 0.0, 1.0),
                     morph=(o, pymupdf.Matrix(c, -sn, sn, c, 0, 0)))


def _find_span(page, rect_unrot, pred):
    import pymupdf

    area = pymupdf.Rect(rect_unrot.x0 - 3, rect_unrot.y0 - 3, rect_unrot.x1 + 3, rect_unrot.y1 + 3)
    return [(s, d) for s, d in _spans(page) if pymupdf.Rect(s["bbox"]).intersects(area) and pred(s["text"])]


def _rewrite(page, spans, edit) -> None:
    """Erase every span of one callout, then write each back through ``edit(text) -> text|None``
    at its own origin and direction. Rewriting the whole callout keeps the text layer
    consistent: removing characters piecemeal strips neighbours whose rotated boxes overlap."""
    import pymupdf

    spans = list(spans)
    for s_, dr in spans:
        page.add_redact_annot(_core(s_, dr), fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    for s_, dr in spans:
        _cover(page, _quad(s_, dr))
    for s_, dr in spans:
        new = edit(s_["text"])
        if new:
            _write(page, s_, dr, new)


def plant_errors(src: Path, dst: Path) -> list[dict]:
    """FTC 07 rev A -> rev B with five documented errors. Locations come from the
    deterministic reader, so they are the drawing's real callouts, not guesses."""
    import pymupdf

    from drawcheck.check import read

    d = read(src, "off")
    doc = pymupdf.open(str(src))
    planted: list[dict] = []

    def log(what, page_no, rule, detail):
        planted.append({"error": what, "page": page_no + 1, "must_catch": rule, "detail": detail})

    # 1. delete one tolerance: the first toleranced Ø.250 callout on sheet 1
    a = next(x for x in d.annotations if x.kind == "dimension" and x.page == 0 and x.text.startswith("Ø.250")
             and x.data.get("tol_type") not in (None, "none"))
    page = doc[0]
    _rewrite(page, _find_span(page, _to_unrotated(page, a.bbox), lambda t: bool(t.strip())),
             lambda t: None if t.strip().startswith(("+", "-")) else t)
    log("Tolerance deleted", 0, "No tolerance to inspect against (FAI-TOL)", f"'{a.text}' becomes 'Ø.250' with no tolerance")

    # 2. undefined datum: the last datum letter of a frame on sheet 2 becomes Z
    f = next(x for x in d.annotations if x.kind == "gdt_frame" and x.page == 1 and x.data.get("datums"))
    letter = f.data["datums"][-1]
    page = doc[1]
    s, dr = _find_span(page, _to_unrotated(page, f.bbox), lambda t: t.strip() == letter)[-1]
    _erase(page, s, dr)
    _write(page, s, dr, s["text"].replace(letter, "Z"))
    log("Datum reference to an undefined datum", 1, "Datum referenced but not defined",
        f"frame '{f.text}': datum {letter} -> Z (no datum Z on the drawing)")

    # 3. change one hole size: 3X Ø.875 ±.010 -> 3X Ø.938 ±.010 (the model still has Ø.875)
    h = next(x for x in d.annotations if x.kind == "dimension" and ".875" in x.text and ".010" in x.text)
    page = doc[h.page]
    _rewrite(page, _find_span(page, _to_unrotated(page, h.bbox), lambda t: ".875" in t and ".010" in t)[:1],
             lambda t: t.replace(".875", ".938"))
    log("Hole size changed", h.page, "Drawing and model disagree (CAD-DIA) + revision compare 'changed'",
        f"'{h.text}' -> Ø.938 ±.010 (the model still has Ø.875)")

    # 4. remove the general profile note (note 4), with the frame text printed in it
    n4 = next(x for x in d.of("note") if "UNTOLERANCED" in x.text.upper())
    page = doc[n4.page]
    box = (n4.bbox[0] - 1, n4.bbox[1] + 1, n4.bbox[2] + 1, n4.bbox[3] - 1)
    for s, dr in _find_span(page, _to_unrotated(page, box), lambda t: bool(t.strip())):
        _erase(page, s, dr)
    log("General tolerance note removed", n4.page, "Untoleranced sizes lose their tolerance (FAI-TOL)",
        f"note '{n4.text[:60]}' deleted")

    # 5. reverse a tolerance: the 2X Ø.250 callout's +.003/-.000 becomes -.003/+.000
    r = next(x for x in d.annotations if x.kind == "dimension" and x.text.startswith("2X Ø.250")
             and x.data.get("tol_type") not in (None, "none"))
    page = doc[r.page]
    def flip(t: str) -> str:
        u = t.strip()
        return (("-" if u[0] == "+" else "+") + u[1:]) if u[:1] in "+-" and len(u) > 1 else t
    _rewrite(page, _find_span(page, _to_unrotated(page, r.bbox), lambda t: bool(t.strip())), flip)
    log("Tolerance limits reversed", r.page, "Tolerance limits reversed (upper below lower)",
        f"'{r.text}' -> upper -.003, lower +.000")

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst), garbage=3, deflate=True)
    doc.close()
    return planted


# ------------------------------------------------------------------ demo 3: assembly

def assembly(box_step: Path, cover_step: Path, out: Path, shift_mm: float = 0.0) -> Path:
    """FTC 07 box with the FTC 08 cover seated on its rim (cover frame Z = box frame Y;
    rim at Y = 12.7 mm). ``shift_mm`` moves the cover along X to plant a misalignment."""
    from build123d import Compound, Location, export_step, import_step

    box = import_step(str(box_step))
    cover = import_step(str(cover_step))
    b = box.moved(Location((0, 0, 0)))
    b.label = "box_ftc07"
    c = cover.moved(Location((shift_mm, 12.7, 0), (1, 0, 0), -90))
    c.label = "cover_ftc08"
    asm = Compound(children=[b, c])
    asm.label = "nist_box_cover"
    out.parent.mkdir(parents=True, exist_ok=True)
    export_step(asm, str(out).replace("\\", "/"))
    return out


def prepare(out: Path, raw: Path | None = None) -> dict:
    raw = download(raw or out.parent / "raw_packages")
    ftc = raw / PACKAGES["ftc"] / FTC
    pmi = raw / PACKAGES["pmi"] / PMI
    d1, d2, d3 = out / "demo1", out / "demo2", out / "demo3"
    for d in (d1, d2, d3):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copy(ftc / "nist_ftc_08_asme1_rc.pdf", d1 / "FTC-08_drawing.pdf")
    shutil.copy(pmi / "nist_ftc_08_asme1_ap242-e2.stp", d1 / "FTC-08_model_AP242.stp")
    shutil.copy(ftc / "nist_ftc_07_asme1_rd.pdf", d1 / "FTC-07_drawing.pdf")
    shutil.copy(pmi / "nist_ftc_07_asme1_ap242-e2.stp", d1 / "FTC-07_model_AP242.stp")

    shutil.copy(ftc / "nist_ftc_07_asme1_rd.pdf", d2 / "FTC-07_revA.pdf")
    shutil.copy(pmi / "nist_ftc_07_asme1_ap242-e2.stp", d2 / "FTC-07_model_AP242.stp")
    planted = plant_errors(ftc / "nist_ftc_07_asme1_rd.pdf", d2 / "FTC-07_revB_PLANTED.pdf")
    (d2 / "planted_errors.json").write_text(json.dumps(planted, indent=2, ensure_ascii=False), encoding="utf-8")

    assembly(ftc / "nist_ftc_07_asme1_rd.stp", ftc / "nist_ftc_08_asme1_rc.stp", d3 / "box_cover_assembly.step")
    assembly(ftc / "nist_ftc_07_asme1_rd.stp", ftc / "nist_ftc_08_asme1_rc.stp",
             d3 / "box_cover_assembly_SHIFTED_1mm.step", shift_mm=1.0)
    (out / "CREDITS.txt").write_text(
        "Test parts: NIST MBE PMI test cases (public, no restrictions on use).\n"
        "https://www.nist.gov/ctl/smart-connected-systems-division/smart-connected-manufacturing-systems-group/mbe-pmi-0\n"
        "Demo 2 rev B and the shifted assembly in demo 3 contain errors planted by OrionFlow; see planted_errors.json.\n",
        encoding="utf-8")
    return {"out": str(out), "planted": planted}


def main() -> None:
    import warnings

    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(prog="fai.demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--out", default="data/nist_demo/kit")
    a = ap.parse_args()
    r = prepare(Path(a.out))
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
