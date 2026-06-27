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
import re
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
    # Vector-like (e.g. Pad.Direction) -> [x, y, z]
    if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z"):
        try:
            return [round(float(v.x), GP), round(float(v.y), GP), round(float(v.z), GP)]
        except Exception:
            pass
    return str(v)


# Whitelist of property *types* that are editable scalar inputs. Type-based
# filtering (not name-based) means new FreeCAD properties are picked up
# automatically while links/shapes/placements/geometry are excluded by nature.
_SCALAR_PROP_TYPES = {
    "App::PropertyLength", "App::PropertyDistance", "App::PropertyFloat",
    "App::PropertyFloatConstraint", "App::PropertyQuantity",
    "App::PropertyQuantityConstraint", "App::PropertyAngle", "App::PropertyArea",
    "App::PropertyVolume", "App::PropertyInteger", "App::PropertyIntegerConstraint",
    "App::PropertyBool", "App::PropertyBoolList", "App::PropertyEnumeration",
    "App::PropertyPercent", "App::PropertyString", "App::PropertyPrecision",
    "App::PropertyVector", "App::PropertyVectorDistance",
}
# Pure-internal props that are editable scalars but carry no design intent.
# This only *shrinks* output; the type whitelist still auto-captures new props.
_PROP_NAME_SKIP = {
    "Label", "Label2", "Visibility", "AttacherEngine", "ArcFitTolerance",
    "MakeInternals", "AllowMultiFace", "AllowCompound", "_Body",
}


def _is_editable_scalar(o, name):
    """True if property ``name`` is an editable scalar input worth recording."""
    try:
        tid = o.getTypeIdOfProperty(name)
    except Exception:
        return False
    if tid not in _SCALAR_PROP_TYPES:
        return False
    try:
        if "Hidden" in (o.getEditorMode(name) or []):
            return False
    except Exception:
        pass
    return True


def _feature_params(o):
    """Editable parameters of a feature.

    Properties are discovered dynamically from ``o.PropertiesList`` and filtered
    to editable scalar inputs (so new FreeCAD props are captured without code
    changes), then the typed structural references the compiler needs
    (ReferenceAxis / Direction / Axis / Originals / Base) are overlaid."""
    t = o.TypeId
    p = {}
    try:
        names = sorted(o.PropertiesList)
    except Exception:
        names = []
    for name in names:
        if name in _PROP_NAME_SKIP:
            continue
        if _is_editable_scalar(o, name):
            try:
                p[name] = _qval(getattr(o, name))
            except Exception:
                continue

    # Typed structural references (link properties, not scalars).
    if t in ("PartDesign::Revolution", "PartDesign::Groove"):
        p["_ReferenceAxis"] = _reference_axis(o)
    elif t == "PartDesign::LinearPattern":
        p["_Direction"] = _reference_axis(o, "Direction")
        p["_Originals"] = _pattern_originals(o)
    elif t == "PartDesign::PolarPattern":
        p["_Axis"] = _reference_axis(o, "Axis")
        p["_Originals"] = _pattern_originals(o)
    elif t == "PartDesign::Thickness":
        base = getattr(o, "Base", None)
        if base and base[0] is not None:
            p["_Base"] = {"object": base[0].Name, "faces": list(base[1])}
    return p


def _reference_axis(o, prop="ReferenceAxis"):
    """Capture a directional link reference (axis/direction) of a feature.

    Covers Revolution/Groove ``ReferenceAxis``, LinearPattern ``Direction`` and
    PolarPattern ``Axis``. Most reference a principal origin axis (X/Y/Z) or a
    sketch construction line / local axis (e.g. ``H_Axis``); ``role`` lets the
    compiler pick the rebuilt body's origin axis when applicable."""
    ra = getattr(o, prop, None)
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


def _pattern_originals(o):
    """Names of the features a transform pattern replicates (``Originals``)."""
    out = []
    for x in getattr(o, "Originals", []) or []:
        name = getattr(x, "Name", None)
        if name:
            out.append(name)
    return out


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
        elif tn == "Ellipse":
            c = g.Center
            rec.update({"type": "Ellipse",
                        "cx": round(float(c.x), GP), "cy": round(float(c.y), GP),
                        "major_radius": round(float(g.MajorRadius), GP),
                        "minor_radius": round(float(g.MinorRadius), GP),
                        "angle_xu": round(float(g.AngleXU), GP)})
        elif tn == "ArcOfEllipse":
            c = g.Center
            rec.update({"type": "ArcOfEllipse",
                        "cx": round(float(c.x), GP), "cy": round(float(c.y), GP),
                        "major_radius": round(float(g.MajorRadius), GP),
                        "minor_radius": round(float(g.MinorRadius), GP),
                        "first": round(float(g.FirstParameter), GP),
                        "last": round(float(g.LastParameter), GP)})
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


def _sketch_external_geometry(o):
    """Resolve a sketch's imported external geometry into local 2D curves.

    External geometry (a curve borrowed from another sketch/body via
    ``addExternal``) closes the profile: a Pad/Pocket over an outer loop plus an
    imported inner loop becomes a ring. FreeCAD stores the resolved curves at the
    tail of ``ExternalGeo`` (after the two principal H/V axes); we pair them with
    the ``ExternalGeometry`` refs by order so the compiler can bake them back in.
    """
    refs = list(getattr(o, "ExternalGeometry", []) or [])
    if not refs:
        return []
    try:
        ext_geo = list(o.ExternalGeo)
    except Exception:
        return []
    tail = ext_geo[-len(refs):] if len(ext_geo) >= len(refs) else ext_geo
    out = []
    for ref, g in zip(refs, tail):
        try:
            src_obj = ref[0]
            subs = list(ref[1]) if len(ref) > 1 else []
            src_name = getattr(src_obj, "Name", "")
        except Exception:
            src_name, subs = "", []
        rec = {"source_object": src_name, "source_subs": subs,
               "construction": bool(getattr(g, "Construction", False))}
        tn = type(g).__name__
        if tn == "Circle":
            c = g.Center
            rec.update({"type": "Circle", "radius": round(float(g.Radius), GP),
                        "cx": round(float(c.x), GP), "cy": round(float(c.y), GP)})
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
        else:
            rec.update({"type": "Other", "class": tn})
        out.append(rec)
    return out


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


_GEO_UNDEF = -2000  # FreeCAD's GeoUndef sentinel for an unused constraint slot.


def _geoid(g):
    """Normalize a constraint GeoId: sentinel -> None; keep -1/-2 (axes) and
    negatives <= -3 (external geometry) and >=0 (real sketch geometry)."""
    try:
        g = int(g)
    except Exception:
        return None
    return None if g <= _GEO_UNDEF else g


def _sketch_constraints(o):
    """Full constraint graph: type, the geometry/vertex slots each constraint
    binds (First/Second/Third + PointPos), driving/reference/active flags, and
    the dimensional value. This is what makes a sketch reconstructable as a graph
    rather than a histogram of constraint types."""
    cons = []
    for i, c in enumerate(o.Constraints):
        rec = {
            "index": i,
            "name": c.Name or "",
            "type": str(c.Type),
            "first": _geoid(getattr(c, "First", _GEO_UNDEF)),
            "first_pos": int(getattr(c, "FirstPos", 0)),
            "second": _geoid(getattr(c, "Second", _GEO_UNDEF)),
            "second_pos": int(getattr(c, "SecondPos", 0)),
            "third": _geoid(getattr(c, "Third", _GEO_UNDEF)),
            "third_pos": int(getattr(c, "ThirdPos", 0)),
            "driving": bool(getattr(c, "Driving", True)),
            "active": bool(getattr(c, "IsActive", True)),
            "virtual_space": bool(getattr(c, "InVirtualSpace", False)),
        }
        val = getattr(c, "Value", None)
        if val is not None:
            try:
                rec["value"] = round(float(val), 6)
            except Exception:
                rec["value"] = None
        cons.append(rec)
    return cons


_EXPR_REF_RE = re.compile(r"<<([^>]+)>>\.(\w+)|\b([A-Za-z_]\w*)\.(\w+)")
# Identifiers that are functions/units, not object references.
_EXPR_NONREFS = {
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sqrt", "pow", "abs",
    "min", "max", "round", "floor", "ceil", "exp", "log", "mod", "hypot",
    "mm", "cm", "m", "deg", "rad", "in", "pi", "e",
}


def _parse_expr_refs(expr):
    """Pull (object, property) references out of a FreeCAD expression string.

    Handles both ``Object.Prop`` and ``<<Label>>.Prop`` forms; this is the edge
    set of the expression graph (design intent linking one feature to another)."""
    objs, props = [], []
    for m in _EXPR_REF_RE.finditer(expr):
        obj = m.group(1) or m.group(3)
        prop = m.group(2) or m.group(4)
        if not obj or obj in _EXPR_NONREFS:
            continue
        if obj not in objs:
            objs.append(obj)
        if prop and prop not in props:
            props.append(prop)
    return objs, props


def _expressions(o):
    out = []
    try:
        ee = o.ExpressionEngine
    except Exception:
        ee = None
    for entry in (ee or []):
        try:
            path, expr = str(entry[0]), str(entry[1])
        except Exception:
            continue
        objs, props = _parse_expr_refs(expr)
        rec = {"object": o.Name, "property": path, "expression": expr,
               "referenced_objects": objs, "referenced_properties": props}
        try:
            res = o.evalExpression(expr)
            rec["result"] = _qval(res)
        except Exception:
            rec["result"] = None
        out.append(rec)
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
                "external_geometry": _sketch_external_geometry(o),
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
        "document": _document_meta(doc),
        "features": features,
        "sketches": sketches,
        "dependencies": deps,
        "constraints": [],
        "expressions": expressions,
    }


def _document_meta(doc):
    """Layer-0 document metadata. Required name/label/object_count plus
    provenance fields (FreeCAD version, UUID, body count, authorship/timestamps)
    that ground the model and preserve engineering naming at the doc level."""
    meta = {
        "name": doc.Name,
        "label": doc.Label,
        "object_count": len(doc.Objects),
    }
    try:
        meta["uuid"] = str(doc.Uid)
    except Exception:
        meta["uuid"] = None
    try:
        meta["freecad_version"] = ".".join(str(x) for x in App.Version()[:3])
    except Exception:
        meta["freecad_version"] = None
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    meta["body_count"] = len(bodies)
    meta["body_names"] = [b.Label for b in bodies]
    for attr, key in (("CreatedBy", "author"), ("CreationDate", "created"),
                      ("LastModifiedBy", "modified_by"), ("LastModifiedDate", "modified"),
                      ("Company", "company"), ("Comment", "comment")):
        try:
            v = getattr(doc, attr, "")
            meta[key] = str(v) if v else None
        except Exception:
            meta[key] = None
    return meta


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
