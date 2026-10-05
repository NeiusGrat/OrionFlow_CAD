"""One inspection run: the six steps of the workflow, each recorded.

    1 upload       files present, hashed, typed
    2 read         drawing -> characteristics, balloons, tolerances
    3 cross_check  drawing vs CAD, drawing vs BOM/PO, unclear callouts
    4 fai_draft    Form 1 / 2 / 3 drafted
    5 review       the quality engineer accepts, edits and signs (not run here)
    6 export       signed forms written (on sign-off, not here)

A failing optional input (an unreadable STEP, a malformed BOM) fails only its
own check, with the reason; the drawing is the one input the run cannot do
without.
"""
from __future__ import annotations

import hashlib
import time
import traceback
from pathlib import Path

from . import ENGINE_VERSION
from .assist import from_env as assistant_from_env

STEPS = [("upload", "Upload"), ("read", "Read drawing"), ("cross_check", "Cross-check"),
         ("fai_draft", "FAI draft"), ("review", "Review & sign"), ("export", "Export & record")]


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class _Steps:
    def __init__(self, progress):
        self.rows = {k: {"id": k, "name": n, "status": "pending"} for k, n in STEPS}
        self.progress = progress or (lambda rows: None)

    def run(self, key: str, fn):
        r = self.rows[key]
        r["status"] = "running"
        self.progress(list(self.rows.values()))
        t0 = time.time()
        try:
            out = fn()
            r["status"] = "done"
            return out
        except Exception as e:
            r.update(status="error", detail=f"{type(e).__name__}: {e}")
            raise
        finally:
            r["duration_s"] = round(time.time() - t0, 2)
            self.progress(list(self.rows.values()))

    def set(self, key: str, **kw):
        self.rows[key].update(kw)
        self.progress(list(self.rows.values()))


def run(drawing: str | Path, step: str | Path | None = None, bom: str | Path | None = None,
        options: dict | None = None, out_dir: str | Path | None = None, progress=None) -> dict:
    from drawcheck.check import check_file
    from interface_check.bom import read_bom

    from . import characteristics as ch
    from .crosscheck import bom_check, cad_check, drawing_findings
    from .forms import build as build_forms

    options = dict(options or {})
    t_start = time.time()
    st = _Steps(progress)
    out_dir = Path(out_dir) if out_dir else None
    assistant = assistant_from_env()
    result: dict = {"engine_version": ENGINE_VERSION, "options": options, "warnings": []}

    def upload():
        files = {"drawing": {"name": Path(drawing).name, "sha256": sha256(drawing)}}
        if step:
            files["step"] = {"name": Path(step).name, "sha256": sha256(step)}
        if bom:
            files["bom"] = {"name": Path(bom).name, "sha256": sha256(bom)}
        result["files"] = files
    st.run("upload", upload)

    def read():
        # Vision only for sheets the text layer cannot read, and only when a
        # model is configured; options["vision"] = "off" forces text-only.
        mode = "off" if options.get("vision") == "off" or not assistant.configured else "scanned"
        report, d = check_file(drawing, vision=mode, model=assistant.model)
        assistant.record(d.vision_stats)
        chars, gt = ch.build(d, options.get("general_class") or None)
        result["title"] = {k: a.text for k, a in d.title.items()}
        result["title_from"] = {k: "title block" for k in result["title"]}
        _title_fallbacks(result, d, drawing)
        result["general_tolerance"] = gt
        if not gt.get("units_stated"):
            result["warnings"].append(
                f"the drawing does not state its units; read as {'inches' if gt['units'] == 'in' else 'millimetres'} "
                + ("from its leading-dot decimals (.250)" if gt["units"] == "in" else "(the default)")
                + " - confirm before inspecting")
        result["notes"] = [{"text": a.text, "number": a.data.get("number")} for a in d.of("note")
                           if not a.data.get("in_title_block")]
        result["drawing"] = {"pages": [{"w": p.width, "h": p.height, "layer": p.layer, "scanned": p.scanned}
                                       for p in d.pages],
                             "warnings": list(d.warnings), "extractors": d.extractors}
        scanned = [p.index for p in d.pages if p.scanned]
        if scanned:
            sheets = ", ".join(str(i + 1) for i in scanned)
            if mode == "off":
                result["warnings"].append(
                    f"sheet(s) {sheets} have no text layer (scanned, or text exported as outlines); with no "
                    "reading model configured their characteristics must be entered by hand")
            else:
                vs = d.vision_stats or {}
                result["warnings"].append(
                    f"sheet(s) {sheets} have no text layer; read by {vs.get('model', assistant.name)} - every "
                    "characteristic from those sheets is marked 'vision' for you to verify")
        result["vision"] = d.vision_stats or None
        return report, d, chars
    report, d, chars = st.run("read", read)
    st.set("read", detail=f"{len(chars)} characteristics, {len(d.pages)} sheet(s)")

    def cross():
        findings = drawing_findings(report, chars)
        cad = None
        if step:
            from .measure import measure
            try:
                m = measure(step, out_dir / "model.glb" if out_dir else None)
                findings += cad_check(chars, m)
                cad = {"extents": m.extents, "volume_mm3": m.volume_mm3, "faces": m.faces, "solids": m.solids,
                       "cylinders": [c.__dict__ for c in m.cylinders], "warnings": m.warnings,
                       "planes": len(m.planes), "candidates": len(m.candidates)}
            except Exception as e:  # noqa: BLE001 - a bad model fails the CAD check only
                result["warnings"].append(f"STEP not measured: {type(e).__name__}: {e}")
                for c in chars:
                    c.cad_status = "no_model"
        else:
            for c in chars:
                c.cad_status = "no_model"
        bom_row = None
        if bom:
            try:
                fs, bom_row = bom_check(result["title"], read_bom(bom))
                findings += fs
            except Exception as e:  # noqa: BLE001
                result["warnings"].append(f"BOM / PO not read: {type(e).__name__}: {e}")
        result["cad"], result["bom_row"] = cad, bom_row
        return findings
    findings = st.run("cross_check", cross)
    order = {"critical": 0, "major": 1, "minor": 2}
    findings.sort(key=lambda f: (order[f.severity], f.char_no or 999))
    st.set("cross_check", detail=f"{len(findings)} findings" + (", CAD measured" if result.get("cad") else ""))

    result["characteristics"] = [c.to_dict() for c in chars]
    result["findings"] = [f.to_dict() for f in findings]
    result["accuracy"] = None
    if step:
        # An AP242 file with semantic PMI is an answer key for the drawing reader.
        try:
            from .score import score
            from .step_pmi import read as read_pmi

            key = read_pmi(step)
            if key["dimensions"] or key["gdt"]:
                key["source"] = Path(options.get("step_name") or step).name
                result["accuracy"] = score(result["characteristics"], key)
        except Exception as e:  # noqa: BLE001 - scoring is a report, never a failure
            result["warnings"].append(f"semantic PMI not read: {type(e).__name__}: {e}")

    def draft():
        result["forms"] = build_forms(result, {"part_number": result["title"].get("drawing_number", ""),
                                               "part_name": result["title"].get("title", "")}, None)
    st.run("fai_draft", draft)
    st.set("review", status="waiting")
    result["steps"] = list(st.rows.values())
    result["has_glb"] = bool(out_dir and (out_dir / "model.glb").exists())
    result["stats"] = {
        "sheets": len(d.pages), "characteristics": len(chars),
        "findings": {s: sum(1 for f in findings if f.severity == s) for s in order},
        "accuracy": None if not result.get("accuracy") else {
            k: result["accuracy"][k] for k in ("total", "matched", "partial", "missed", "recall",
                                                "recall_with_partial", "precision")},
        "runtime_s": round(time.time() - t_start, 2), "model": assistant.name,
        "cost_usd": round(assistant.usage.cost_usd, 4), "engine_version": ENGINE_VERSION,
    }
    return result


def _title_fallbacks(result: dict, d, drawing) -> None:
    """Model-based sheets often carry no title block. Fill what can be read safely,
    and say where each value came from so Form 1 never presents a guess as data."""
    import re

    t, src = result["title"], result["title_from"]
    if not t.get("drawing_number") and not t.get("part_number"):
        t["drawing_number"] = Path(drawing).stem
        src["drawing_number"] = "file name"
    if not t.get("revision"):
        for p in d.pages:
            for ln in p.lines:
                m = re.fullmatch(r"\s*REV(?:ISION)?\.?\s*[:\-]?\s*([A-Z]{1,2}|\d{1,2})\s*", ln.text, re.I)
                if m:
                    t["revision"] = m.group(1).upper()
                    src["revision"] = f"sheet {p.index + 1} text"
                    return


def run_safe(*a, **kw) -> dict:
    try:
        return run(*a, **kw) | {"status": "done"}
    except Exception as e:  # noqa: BLE001 - the run records its own failure
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=5),
                "engine_version": ENGINE_VERSION}
