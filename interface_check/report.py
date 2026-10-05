"""Report -> JSON, PDF, and a GLB whose mesh nodes are named by instance path.

The GLB is what the report page's viewer loads: clicking a finding highlights
the nodes named in its ``instances`` and zooms to its ``location``.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from .models import SEVERITIES, Instance, Report

SEV_COLOUR = {"high": (0.75, 0.1, 0.1), "medium": (0.85, 0.45, 0.0), "low": (0.3, 0.3, 0.3), "info": (0.2, 0.35, 0.6)}


def write_json(report: Report, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def tessellate(shape, tolerance: float = 0.2) -> tuple:
    """Vertices (mm) and triangles of a placed shape, outward-wound."""
    import numpy as np
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    from .features import faces

    BRepMesh_IncrementalMesh(shape, tolerance, False, 0.3, True)
    verts, tris, base = [], [], 0
    for f in faces(shape):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        for i in range(1, tri.NbNodes() + 1):
            p = tri.Node(i).Transformed(trsf)
            verts.append((p.X(), p.Y(), p.Z()))
        rev = f.Orientation() == TopAbs_REVERSED
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            tris.append((base + a - 1, base + c - 1, base + b - 1) if rev else (base + a - 1, base + b - 1, base + c - 1))
        base += tri.NbNodes()
    return np.array(verts, dtype=float).reshape(-1, 3), np.array(tris, dtype=int).reshape(-1, 3)


def write_glb(instances: list[Instance], path: str | Path, tolerance: float = 0.2) -> Path:
    import trimesh

    scene = trimesh.Scene()
    for inst in instances:
        v, t = tessellate(inst.shape, tolerance)
        if not len(t):
            continue
        mesh = trimesh.Trimesh(v / 1000.0, t, process=False)       # glTF is metres
        scene.add_geometry(mesh, node_name=inst.path, geom_name=inst.path)
    if not scene.geometry:
        raise ValueError("nothing to tessellate for the 3D view")
    path = Path(path)
    path.write_bytes(scene.export(file_type="glb"))
    return path


def write_pdf(report: Report, path: str | Path) -> Path:
    import pymupdf

    d = report.to_dict()
    doc = pymupdf.open()
    W, H, M = 595, 842, 40
    state = {"page": None, "y": H}

    def page():
        state["page"] = doc.new_page(width=W, height=H)
        state["y"] = M

    def line(text: str, size: float = 9, colour=(0, 0, 0), bold: bool = False, indent: float = 0, wrap: int = 105):
        for chunk in textwrap.wrap(text, wrap - int(indent / 5)) or [""]:
            if state["page"] is None or state["y"] > H - M:
                page()
            state["page"].insert_text((M + indent, state["y"]), chunk, fontsize=size, color=colour,
                                      fontname="hebo" if bold else "helv")
            state["y"] += size * 1.35

    src = d["source"]
    line("Interface Check report", 16, bold=True)
    line(f"Assembly {src['step']}" + (f"   BOM {src['bom']}" if src.get("bom") else "")
         + (f"   previous {src['prev_step']}" if src.get("prev_step") else "")
         + (f"   URDF {src['urdf']}" if src.get("urdf") else ""), 9)
    st = d["stats"]
    line(f"{st.get('parts', 0)} parts, {st.get('instances', 0)} instances, {st.get('interfaces', 0)} interfaces, "
         f"{st.get('runtime_s', 0)} s, LLM calls {d['llm_usage'].get('calls', 0)}", 9)
    s = d["summary"]
    line("Findings: " + ", ".join(f"{s[k]} {k}" for k in SEVERITIES), 11, bold=True)
    state["y"] += 4
    if d["assumptions"]:
        line("Assumptions", 10, bold=True)
        for a in d["assumptions"]:
            line("- " + a, 8, indent=8)
        state["y"] += 4
    for sev in SEVERITIES:
        fs = [f for f in d["findings"] if f["severity"] == sev]
        if not fs:
            continue
        line(f"{sev.upper()} ({len(fs)})", 11, SEV_COLOUR[sev], bold=True)
        for f in fs:
            tag = f" [{f['change_status']}]" if f.get("change_status") else ""
            line(f"{f['rule_id']}{tag}", 9, SEV_COLOUR[sev], bold=True, indent=8)
            line(f["message"], 8.5, indent=16)
            if f["instances"]:
                line("Parts: " + ", ".join(f["instances"][:6]), 7.5, (0.3, 0.3, 0.3), indent=16)
            if f["measured"] or f["expected"]:
                line(f"Measured {json.dumps(f['measured'])}   expected {json.dumps(f['expected'])}", 7.5,
                     (0.3, 0.3, 0.3), indent=16)
            if f.get("location"):
                line(f"At {f['location']} mm", 7.5, (0.3, 0.3, 0.3), indent=16)
            state["y"] += 3
    if d["changes"]:
        line("Revision changes", 11, bold=True)
        for c in d["changes"]:
            line(f"{c['part']}: {c['status']}" + (f" (was {c['old_name']})" if c["old_name"] and c["old_name"] != c["part"]
                                                   else ""), 9, bold=True, indent=8)
            for det in c["details"][:8]:
                line("- " + det, 8, indent=16)
            if c["neighbours"]:
                line("Needs a look: " + ", ".join(c["neighbours"]), 8, (0.3, 0.3, 0.3), indent=16)
    if d.get("fixed"):
        line(f"Fixed since the previous revision ({len(d['fixed'])})", 11, bold=True)
        for f in d["fixed"]:
            line(f"{f['rule_id']}: {f['message']}", 8, indent=8)
    path = Path(path)
    doc.save(str(path))
    return path
