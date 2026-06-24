"""Deterministic FCStd -> raw FeatureGraph extractor.

RUNS UNDER FREECAD'S PYTHON ONLY (it ``import FreeCAD``). It is intentionally
standalone (stdlib + FreeCAD), so the orchestrator can invoke it as a subprocess
with FreeCAD's interpreter without putting the project package on PYTHONPATH.

Usage:
    freecad_python fcstd_parser.py --manifest manifest.json --out raw_extract/
    freecad_python fcstd_parser.py --fcstd a.FCStd --id 1234 --out raw_extract/

Manifest is a JSON list of {"id": "...", "fcstd": "abs/path.FCStd"}.
Emits one ``<id>.json`` per input (raw graph, or {"error": ...} on failure).
"""

import argparse
import json
import os
import sys

import FreeCAD as App  # type: ignore

SCHEMA_VERSION = "ofl_fcstd_v1"
# Geometry coordinate precision (decimals). Must stay well below FreeCAD's wire
# weld tolerance (~1e-7) so adjacent edges reconnect into one closed profile;
# 6-decimal rounding splits gear profiles into open wires and Pads fail.
GP = 12
BOILERPLATE_TYPES = {
    "App::Origin", "App::Line", "App::Plane", "App::Point",
    "App::DocumentObjectGroup",
}


def _short_type(type_id):
    if type_id == "Sketcher::SketchObject":
        return "Sketch"
    return type_id.split("::")[-1]


def _qval(v):
    """Coerce a FreeCAD property to a JSON scalar (Quantity -> float mm)."""
    if hasattr(v, "Value"):
        try:
            return float(v.Value)
        except Exception:
            pass
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, str)):
        return v
    return str(v)


def _feature_params(o):
    """Editable parameters per PartDesign feature type."""
    t = o.TypeId
    p = {}
    if t in ("PartDesign::Pad", "PartDesign::Pocket"):
        for prop in ("Length", "Length2", "Type", "Reversed", "Midplane", "Offset"):
            if hasattr(o, prop):
                p[prop] = _qval(getattr(o, prop))
    elif t == "PartDesign::Fillet":
        if hasattr(o, "Radius"):
            p["Radius"] = _qval(o.Radius)
    elif t == "PartDesign::Chamfer":
        for prop in ("Size", "Size2", "Angle", "ChamferType"):
            if hasattr(o, prop):
                p[prop] = _qval(getattr(o, prop))
    elif t in ("PartDesign::Revolution", "PartDesign::Groove"):
        for prop in ("Angle", "Midplane", "Reversed"):
            if hasattr(o, prop):
                p[prop] = _qval(getattr(o, prop))
        p["_ReferenceAxis"] = _reference_axis(o)
    elif t == "PartDesign::LinearPattern":
        for prop in ("Occurrences", "Length", "Reversed"):
            if hasattr(o, prop):
                p[prop] = _qval(getattr(o, prop))
    elif t == "PartDesign::PolarPattern":
        for prop in ("Occurrences", "Angle", "Reversed"):
            if hasattr(o, prop):
                p[prop] = _qval(getattr(o, prop))
    elif t == "PartDesign::Hole":
        for prop in ("Diameter", "Depth", "DepthType", "DrillPoint", "DrillPointAngle",
                     "ThreadType", "Tapered", "Reversed"):
            if hasattr(o, prop):
                p[prop] = _qval(getattr(o, prop))
    elif t == "PartDesign::Thickness":
        for prop in ("Value", "Mode", "Join", "Reversed", "Intersection"):
            if hasattr(o, prop):
                p[prop] = _qval(getattr(o, prop))
        base = getattr(o, "Base", None)
        if base and base[0] is not None:
            p["_Base"] = {"object": base[0].Name, "faces": list(base[1])}
    return p


def _reference_axis(o):
    """Capture a feature's ReferenceAxis (for Revolution/Groove).

    Most parts revolve around a principal origin axis (X/Y/Z); some use a sketch
    construction line. ``role`` lets the compiler pick the rebuilt body's axis."""
    ra = getattr(o, "ReferenceAxis", None)
    if not ra or ra[0] is None:
        return None
    obj, subs = ra[0], list(ra[1]) if len(ra) > 1 else [""]
    name = getattr(obj, "Name", "")
    role = name if name in ("X_Axis", "Y_Axis", "Z_Axis") else None
    return {
        "object": name,
        "type_id": getattr(obj, "TypeId", ""),
        "subs": subs,
        "role": role,
        "is_sketch": getattr(obj, "TypeId", "") == "Sketcher::SketchObject",
    }


def _guess_plane(o):
    """Best-effort construction plane label for a sketch."""
    sup = getattr(o, "AttachmentSupport", None) or getattr(o, "Support", None)
    if sup:
        try:
            ref = sup[0][0]
            faces = sup[0][1]
            return "face:%s:%s" % (ref.Name, ",".join(faces) if faces else "")
        except Exception:
            return "attached"
    # No support -> base plane. Infer from placement normal.
    try:
        zdir = o.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        ax = (abs(zdir.x), abs(zdir.y), abs(zdir.z))
        dom = ax.index(max(ax))
        return {0: "YZ", 1: "XZ", 2: "XY"}[dom]
    except Exception:
        return "XY"


def _sketch_geometry(o):
    geoms = []
    for i, g in enumerate(o.Geometry):
        tn = type(g).__name__
        rec = {"index": i, "construction": bool(getattr(g, "Construction", False))}
        if tn == "Circle":
            c = g.Center
            rec.update({"type": "Circle", "radius": round(float(g.Radius), GP),
                        "cx": round(float(c.x), GP), "cy": round(float(c.y), GP),
                        "cz": round(float(c.z), GP)})
        elif tn == "ArcOfCircle":
            c = g.Center
            rec.update({"type": "ArcOfCircle", "radius": round(float(g.Radius), GP),
                        "cx": round(float(c.x), GP), "cy": round(float(c.y), GP),
                        "first": round(float(g.FirstParameter), GP),
                        "last": round(float(g.LastParameter), GP)})
        elif tn in ("LineSegment", "Line"):
            s, e = g.StartPoint, g.EndPoint
            rec.update({"type": "LineSegment",
                        "sx": round(float(s.x), GP), "sy": round(float(s.y), GP),
                        "ex": round(float(e.x), GP), "ey": round(float(e.y), GP)})
        elif tn == "Point":
            rec.update({"type": "Point", "x": round(float(g.X), GP), "y": round(float(g.Y), GP)})
        elif tn == "BSplineCurve":
            poles = g.getPoles()
            rec.update({
                "type": "BSpline",
                "degree": int(g.Degree),
                "periodic": bool(g.isPeriodic()),
                "closed": bool(g.isClosed()),
                "rational": bool(g.isRational()),
                "poles": [[round(p.x, GP), round(p.y, GP), round(p.z, GP)] for p in poles],
                "weights": [round(float(w), GP) for w in g.getWeights()],
                "knots": [round(float(k), GP) for k in g.getKnots()],
                "mults": [int(m) for m in g.getMultiplicities()],
            })
        elif tn == "BezierCurve":
            poles = g.getPoles()
            rec.update({
                "type": "Bezier",
                "degree": int(g.Degree),
                "poles": [[round(p.x, GP), round(p.y, GP), round(p.z, GP)] for p in poles],
                "weights": [round(float(w), GP) for w in g.getWeights()],
            })
        else:
            rec.update({"type": "Other", "class": tn})
        geoms.append(rec)
    return geoms


def _sketch_bbox(o):
    """Union bounding box of all sketch edges in the sketch's local frame.

    Uses each edge's real shape bounds, so it covers BSplines/arcs/circles
    uniformly (important for gear/spline profiles where ``outer_diameter`` is a
    bbox span rather than a single circle)."""
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    for g in o.Geometry:
        try:
            bb = g.toShape().BoundBox
        except Exception:
            continue
        xmin, ymin = min(xmin, bb.XMin), min(ymin, bb.YMin)
        xmax, ymax = max(xmax, bb.XMax), max(ymax, bb.YMax)
    if xmin == float("inf"):
        return None
    return {
        "xmin": round(xmin, 6), "xmax": round(xmax, 6),
        "ymin": round(ymin, 6), "ymax": round(ymax, 6),
        "span_x": round(xmax - xmin, 6), "span_y": round(ymax - ymin, 6),
    }


def _sketch_constraints(o):
    cons = []
    for i, c in enumerate(o.Constraints):
        rec = {"index": i, "name": c.Name or "", "type": str(c.Type)}
        val = getattr(c, "Value", None)
        if val is not None:
            try:
                rec["value"] = round(float(val), 6)
            except Exception:
                rec["value"] = None
        cons.append(rec)
    return cons


def _expressions(o):
    out = []
    try:
        ee = o.ExpressionEngine
    except Exception:
        ee = None
    for entry in (ee or []):
        try:
            path, expr = entry[0], entry[1]
        except Exception:
            continue
        out.append({"object": o.Name, "property": str(path), "expression": str(expr)})
    return out


def extract(doc):
    """Build a raw FeatureGraph dict (no recovered ``parameters``)."""
    kept = [o for o in doc.Objects if o.TypeId not in BOILERPLATE_TYPES]
    kept_names = {o.Name for o in kept}

    features, sketches, expressions = [], [], []
    for o in kept:
        if o.TypeId == "Sketcher::SketchObject":
            sketches.append({
                "id": o.Name,
                "plane": _guess_plane(o),
                "support": _guess_plane(o) if str(getattr(o, "MapMode", "")) != "Deactivated" else None,
                "placement": _placement(o),
                "global_placement": _global_placement(o),
                "bbox": _sketch_bbox(o),
                "geometry": _sketch_geometry(o),
                "constraints": _sketch_constraints(o),
            })
        features.append({
            "id": o.Name,
            "type": _short_type(o.TypeId),
            "type_id": o.TypeId,
            "label": o.Label,
            "parameters": _feature_params(o),
        })
        expressions.extend(_expressions(o))

    deps = []
    for o in kept:
        # profile: sketch -> feature
        prof = getattr(o, "Profile", None)
        if prof:
            try:
                sk = prof[0]
                if sk is not None and sk.Name in kept_names:
                    deps.append({"source": sk.Name, "target": o.Name, "kind": "profile"})
            except Exception:
                pass
        # base: previous solid -> feature
        base = getattr(o, "BaseFeature", None)
        if base is not None and getattr(base, "Name", None) in kept_names:
            deps.append({"source": base.Name, "target": o.Name, "kind": "base"})

    return {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "name": doc.Name,
            "label": doc.Label,
            "object_count": len(doc.Objects),
        },
        "features": features,
        "sketches": sketches,
        "dependencies": deps,
        "constraints": [],
        "expressions": expressions,
    }


def _placement(o):
    try:
        pos = o.Placement.Base
        rot = o.Placement.Rotation
        return {
            "pos": [round(pos.x, 6), round(pos.y, 6), round(pos.z, 6)],
            "axis": [round(rot.Axis.x, 6), round(rot.Axis.y, 6), round(rot.Axis.z, 6)],
            "angle": round(float(rot.Angle), 6),
        }
    except Exception:
        return {}


def _global_placement(o):
    """Resolved world placement of a sketch (quaternion form, deg/rad-safe).

    This is what makes faithful reconstruction possible: face-attached sketches
    have local pos (0,0,0) but live at a real world Z with a flipped normal."""
    try:
        gp = o.getGlobalPlacement()
        b = gp.Base
        q = gp.Rotation.Q
        return {
            "pos": [round(b.x, 6), round(b.y, 6), round(b.z, 6)],
            "q": [round(q[0], 8), round(q[1], 8), round(q[2], 8), round(q[3], 8)],
        }
    except Exception:
        return None


def parse_file(fcstd_path, source_id):
    doc = App.openDocument(fcstd_path)
    try:
        raw = extract(doc)
        raw["source_id"] = source_id
        return raw
    finally:
        App.closeDocument(doc.Name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--fcstd")
    ap.add_argument("--id")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.manifest:
        items = json.load(open(args.manifest, "r", encoding="utf-8"))
    elif args.fcstd:
        items = [{"id": args.id or os.path.splitext(os.path.basename(args.fcstd))[0],
                  "fcstd": args.fcstd}]
    else:
        ap.error("need --manifest or --fcstd")

    ok = err = 0
    for it in items:
        sid, path = it["id"], it["fcstd"]
        out_path = os.path.join(args.out, sid + ".json")
        try:
            raw = parse_file(path, sid)
            json.dump(raw, open(out_path, "w", encoding="utf-8"), indent=2)
            ok += 1
            sys.stdout.write("OK %s features=%d sketches=%d deps=%d\n" % (
                sid, len(raw["features"]), len(raw["sketches"]), len(raw["dependencies"])))
        except Exception as e:  # noqa: BLE001
            json.dump({"source_id": sid, "error": "%s: %s" % (type(e).__name__, e)},
                      open(out_path, "w", encoding="utf-8"), indent=2)
            err += 1
            sys.stdout.write("ERR %s %s\n" % (sid, e))
        sys.stdout.flush()
    sys.stdout.write("DONE ok=%d err=%d\n" % (ok, err))


if __name__ == "__main__":
    main()
