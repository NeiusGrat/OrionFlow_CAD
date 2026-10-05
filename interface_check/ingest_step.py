"""STEP assembly -> part definitions and placed instances, in millimetres.

XCAF, not a plain STEP import: it keeps part names, the assembly tree and each
copy's placement, and every later check needs all three. A plain import gives
one compound of anonymous solids.

Exports are messier than the format allows, so three repairs happen here and
each is reported rather than hidden:

* **Flattened files.** One free shape holding many solids and no assembly tree
  (a "save as one body" export). Each solid becomes its own part, and the
  report says the structure was missing, because instance counts are then
  counts of identical solids rather than of placed copies.
* **Duplicated definitions.** Exporters that write one definition per copy
  (build123d, some Fusion exports) would make every copy its own part with
  quantity 1. Definitions with the same name *and* the same geometric
  signature are merged, so quantities count copies.
* **Broken solids.** A part that fails ``BRepCheck`` or has no closed volume
  is kept and flagged; it never stops the run.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence, TDF_Tool
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

from .models import Finding, Instance, Part


class StepReadError(ValueError):
    pass


def _name(label) -> str:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString().strip()
    return ""


def _entry(label) -> str:
    s = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, s)
    return s.ToCString()


def matrix(loc) -> np.ndarray:
    t = loc.Transformation()
    m = np.eye(4)
    for r in range(3):
        for c in range(4):
            m[r, c] = t.Value(r + 1, c + 1)
    return m


def solids(shape) -> list:
    out, exp = [], TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        out.append(exp.Current())
        exp.Next()
    return out


def signature(shape) -> dict:
    """Volume, area and sorted bounding-box sides: identity that survives renames."""
    vp, sp = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vp)
    BRepGProp.SurfaceProperties_s(shape, sp)
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    if b.IsVoid():
        sides = [0.0, 0.0, 0.0]
    else:
        x0, y0, z0, x1, y1, z1 = b.Get()
        sides = sorted([x1 - x0, y1 - y0, z1 - z0])
    return {"volume": abs(vp.Mass()), "area": sp.Mass(), "bbox": [round(s, 3) for s in sides]}


def same_signature(a: dict, b: dict, rel: float = 0.01) -> bool:
    def close(x, y):
        return abs(x - y) <= rel * max(abs(x), abs(y), 1e-6)
    return (close(a["volume"], b["volume"]) and close(a["area"], b["area"])
            and all(close(x, y) or abs(x - y) < 0.01 for x, y in zip(a["bbox"], b["bbox"])))


#: Full BRepCheck above this many faces costs more than the rest of the part's
#: analysis; it is skipped and the part is marked unverified, not valid.
VALIDITY_MAX_FACES = 20000


def face_count(shape) -> int:
    n, exp = 0, TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        n += 1
        exp.Next()
    return n


def _validate(part: Part) -> None:
    if not solids(part.shape):
        has_shell = TopExp_Explorer(part.shape, TopAbs_SHELL).More()
        part.problems.append("no solid body (surface or mesh exported as STEP)" if has_shell
                             else "empty shape")
    elif face_count(part.shape) > VALIDITY_MAX_FACES:
        part.signature["validity"] = "unchecked: too many faces for a full BRepCheck"
    elif not BRepCheck_Analyzer(part.shape).IsValid():
        part.problems.append("BRepCheck reports an invalid solid")
    if part.signature.get("volume", 0) <= 1e-6 and not part.problems:
        part.problems.append("zero volume")
    part.valid = not part.problems


#: Names exporters write when the user gave none: OCCT reference ids, kernel
#: type words, AP214 usage ids. A part is named after its nearest real name.
_GENERIC = re.compile(r"^(=>\[[\d:]+\]|solid|compound|shell|comp[-_ ]?solid|body|nauo\d*|"
                      r"open cascade.*|unnamed.*|)$", re.I)


def _real(name: str) -> str:
    return "" if _GENERIC.match(name or "") else name


def _base_name(name: str) -> str:
    """'bracket <2>', 'bracket (2)', 'bracket:2' -> 'bracket' (instance decorations)."""
    return re.sub(r"\s*(<\d+>|\(\d+\)|:\d+)$", "", name).strip()


def read_assembly(path: str | Path) -> tuple[dict[str, Part], list[Instance], list[Finding]]:
    path = Path(path)
    if not path.exists():
        raise StepReadError(f"no such file: {path}")
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise StepReadError(f"cannot read STEP: {path.name}")
    if not reader.Transfer(doc):
        raise StepReadError(f"STEP transfer failed: {path.name}")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    parts: dict[str, Part] = {}
    instances: list[Instance] = []
    findings: list[Finding] = []

    def add_instance(pid, label_name, shape, loc, ipath):
        if pid not in parts:
            parts[pid] = Part(pid, label_name or f"part_{len(parts) + 1}", shape)
        instances.append(Instance(f"i{len(instances)}", pid, ipath, shape.Moved(loc), matrix(loc), loc))

    def walk(label, loc, ipath, owner):
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, comps, False)
            for i in range(1, comps.Length() + 1):
                comp = comps.Value(i)
                ref = TDF_Label()
                XCAFDoc_ShapeTool.GetReferredShape_s(comp, ref)
                child = loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(comp))
                seg = _real(_name(comp)) or _real(_name(ref))
                walk(ref, child, f"{ipath}/{seg}" if seg else ipath, seg or owner)
        else:
            own = _real(_name(label))
            if not own and ipath.rsplit("/", 1)[-1] != owner:
                ipath = f"{ipath}/{owner}"
            add_instance(_entry(label), own or owner, XCAFDoc_ShapeTool.GetShape_s(label), loc, ipath)

    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    if roots.Length() == 0:
        raise StepReadError(f"no shapes in {path.name}")
    flat = roots.Length() == 1 and not XCAFDoc_ShapeTool.IsAssembly_s(roots.Value(1))
    if flat:
        root = roots.Value(1)
        shape = XCAFDoc_ShapeTool.GetShape_s(root)
        bodies = solids(shape)
        base = _real(_name(root)) or path.stem
        if len(bodies) > 1:
            findings.append(Finding(
                "ASSEMBLY_STRUCTURE_MISSING", "medium", [base],
                f"{path.name} has no assembly tree: one shape with {len(bodies)} solids. "
                "Each solid is treated as its own part; quantities are counts of identical solids.",
                measured={"solids": len(bodies)}, source="geometry"))
            for k, body in enumerate(bodies):
                add_instance(f"solid{k}", f"{base}_solid{k + 1}", body, TopLoc_Location(),
                             f"{base}/{base}_solid{k + 1}")
        else:
            add_instance(_entry(root), base, shape, TopLoc_Location(), base)
    else:
        for i in range(1, roots.Length() + 1):
            root = roots.Value(i)
            top = _real(_name(root)) or path.stem
            walk(root, TopLoc_Location(), top, top)

    for p in parts.values():
        p.signature = signature(p.shape)
        _validate(p)
    _merge_duplicate_definitions(parts, instances, flat)
    _unique_paths(instances)

    for p in parts.values():
        if not p.valid:
            paths = [i.path for i in instances if i.part_id == p.part_id]
            findings.append(Finding(
                "PART_INVALID", "high", paths[:5],
                f"{p.name}: {'; '.join(p.problems)}. Geometry checks on it are unreliable.",
                parts=[p.name], measured={"problems": p.problems}))
    return parts, instances, findings


def _merge_duplicate_definitions(parts: dict[str, Part], instances: list[Instance], flat: bool) -> None:
    """Fold definitions with the same name and geometry into one part.

    In a flattened file names are synthetic, so geometry alone decides — the
    first solid's name is kept for the group.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for pid, p in parts.items():
        key = "" if flat else _base_name(p.name).lower()
        for lead in groups[key]:
            if same_signature(parts[lead].signature, p.signature):
                remap = lead
                break
        else:
            groups[key].append(pid)
            continue
        for inst in instances:
            if inst.part_id == pid:
                inst.part_id = remap
    used = {i.part_id for i in instances}
    for pid in list(parts):
        if pid not in used:
            del parts[pid]
    if flat:
        for pid, p in parts.items():
            p.name = re.sub(r"_solid\d+$", "", p.name) + f"_body{list(parts).index(pid) + 1}"


def _unique_paths(instances: list[Instance]) -> None:
    seen: dict[str, int] = defaultdict(int)
    for inst in instances:
        seen[inst.path] += 1
    count: dict[str, int] = defaultdict(int)
    for inst in instances:
        if seen[inst.path] > 1:
            count[inst.path] += 1
            inst.path = f"{inst.path}#{count[inst.path]}"
