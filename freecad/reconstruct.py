"""Phase 2 — deterministic FeatureGraph -> FCStd reconstruction compiler.

RUNS UNDER FREECAD'S PYTHON ONLY. Compiles a FeatureGraph directly into native
FreeCAD PartDesign feature history (editable sketches + pads + pockets) — NOT a
static B-Rep, and with no STEP import/export. Feature order is preserved.

Vocabulary (Phase 2): Body, Sketch (Circle/LineSegment/ArcOfCircle), Pad, Pocket.
This set reconstructs ~83% of the gNucleus dataset.

Usage:
    freecad_python reconstruct.py --graph sample.json --out out.FCStd
    freecad_python reconstruct.py --manifest m.json --out-dir rebuilt/ [--roundtrip]

``--roundtrip`` re-extracts each rebuilt FCStd (via fcstd_parser.extract) and
writes a comparison report next to it.
"""

import argparse
import json
import os
import sys

import FreeCAD as App  # type: ignore
import Part  # type: ignore

SUPPORTED = {"Body", "Sketch", "Pad", "Pocket", "Revolution", "Groove", "Hole",
             "Thickness", "LinearPattern", "PolarPattern"}
_KIND = {
    "Pad": "PartDesign::Pad",
    "Pocket": "PartDesign::Pocket",
    "Revolution": "PartDesign::Revolution",
    "Groove": "PartDesign::Groove",
    "Hole": "PartDesign::Hole",
    "LinearPattern": "PartDesign::LinearPattern",
    "PolarPattern": "PartDesign::PolarPattern",
}
_PROFILE_OPS = {"Pad", "Pocket", "Revolution", "Groove", "Hole"}
_TRANSFORM_OPS = {"LinearPattern", "PolarPattern"}


def _origin_axis(body, role):
    """Return the rebuilt body's origin axis (X/Y/Z) matching ``role``."""
    try:
        for f in body.Origin.OriginFeatures:
            if getattr(f, "Role", "") == role:
                return f
    except Exception:
        pass
    return None


def _plane_placement(plane, z=0.0):
    """Placement that puts a sketch on a principal plane at height ``z``."""
    if plane == "XZ":
        rot = App.Rotation(App.Vector(1, 0, 0), 90)
    elif plane == "YZ":
        rot = App.Rotation(App.Vector(0, 1, 0), -90)
    else:  # XY (and any face-attached sketch, placed flat at height z)
        rot = App.Rotation()
    return App.Placement(App.Vector(0, 0, z), rot)


def _add_geometry(sketch, geom_list):
    for g in geom_list:
        t = g.get("type")
        cons = bool(g.get("construction", False))
        try:
            if t == "Circle":
                c = App.Vector(g["cx"], g["cy"], 0)
                sketch.addGeometry(Part.Circle(c, App.Vector(0, 0, 1), g["radius"]), cons)
            elif t == "LineSegment":
                a = App.Vector(g["sx"], g["sy"], 0)
                b = App.Vector(g["ex"], g["ey"], 0)
                sketch.addGeometry(Part.LineSegment(a, b), cons)
            elif t == "ArcOfCircle":
                c = App.Vector(g["cx"], g["cy"], 0)
                circ = Part.Circle(c, App.Vector(0, 0, 1), g["radius"])
                sketch.addGeometry(Part.ArcOfCircle(circ, g["first"], g["last"]), cons)
            elif t == "BSpline":
                poles = [App.Vector(*p) for p in g["poles"]]
                bs = Part.BSplineCurve()
                if g.get("rational") and g.get("weights"):
                    bs.buildFromPolesMultsKnots(poles, g["mults"], g["knots"],
                                                g["periodic"], g["degree"], g["weights"])
                else:
                    bs.buildFromPolesMultsKnots(poles, g["mults"], g["knots"],
                                                g["periodic"], g["degree"])
                sketch.addGeometry(bs, cons)
            elif t == "Bezier":
                poles = [App.Vector(*p) for p in g["poles"]]
                bz = Part.BezierCurve()
                bz.setPoles(poles)
                sketch.addGeometry(bz, cons)
            # Point / Other: skipped.
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"  geom {t} skipped: {e}\n")


def compile_graph(graph, doc_name="rebuilt"):
    """Build a FreeCAD document from a FeatureGraph. Returns (doc, report)."""
    report = {"unsupported": [], "recompute_errors": [], "built": []}
    doc = App.newDocument(doc_name)
    body = doc.addObject("PartDesign::Body", "Body")

    # profile sketch per solid feature, from dependency 'profile' edges
    profile_of = {d["target"]: d["source"]
                  for d in graph.get("dependencies", []) if d["kind"] == "profile"}

    sketches = {sk["id"]: sk for sk in graph.get("sketches", [])}
    built_sketches = {}
    built_solids = {}
    current_top = 0.0
    have_solid = False

    for feat in graph.get("features", []):
        fid, ftype = feat["id"], feat["type"]
        if ftype == "Body":
            continue
        if ftype not in SUPPORTED:
            report["unsupported"].append({"id": fid, "type": ftype})
            continue

        if ftype == "Sketch":
            sk = sketches.get(fid, {"plane": "XY", "geometry": []})
            obj = doc.addObject("Sketcher::SketchObject", fid)
            body.addObject(obj)
            gp = sk.get("global_placement")
            if gp and gp.get("q"):
                # Faithful: place the sketch at its resolved world placement so
                # face-attached sketches land at the right Z with the right normal.
                q = gp["q"]
                obj.Placement = App.Placement(
                    App.Vector(*gp["pos"]), App.Rotation(q[0], q[1], q[2], q[3]))
            else:
                plane = sk.get("plane", "XY")
                z = 0.0 if (not have_solid and plane in ("XY", "XZ", "YZ")) else current_top
                obj.Placement = _plane_placement(plane if plane in ("XY", "XZ", "YZ") else "XY", z)
            _add_geometry(obj, sk.get("geometry", []))
            # Bake imported external geometry as real edges so ring/cutout
            # profiles (outer loop + borrowed inner loop) close into a face.
            _add_geometry(obj, sk.get("external_geometry", []))
            built_sketches[fid] = obj
            doc.recompute()
            continue

        params = feat.get("parameters", {})

        # Thickness: a dressup on a face of a prior feature (no profile sketch).
        if ftype == "Thickness":
            base_ref = params.get("_Base") or {}
            base_obj = built_solids.get(base_ref.get("object"))
            if base_obj is None:
                report["recompute_errors"].append({"id": fid, "error": "missing thickness base"})
                continue
            op = doc.addObject("PartDesign::Thickness", fid)
            op.Base = (base_obj, base_ref.get("faces", []))
            if isinstance(params.get("Value"), (int, float)):
                op.Value = float(params["Value"])
            for prop in ("Mode", "Join"):
                if params.get(prop) is not None:
                    try:
                        setattr(op, prop, params[prop])
                    except Exception:
                        pass
            if "Reversed" in params:
                op.Reversed = bool(params["Reversed"])
            body.addObject(op)
            doc.recompute()
            if op.State and "Invalid" in op.State:
                report["recompute_errors"].append({"id": fid, "error": "invalid after recompute"})
            else:
                report["built"].append({"id": fid, "type": ftype})
                built_solids[fid] = op
                try:
                    current_top = body.Shape.BoundBox.ZMax
                except Exception:
                    pass
            continue

        # Transform feature: LinearPattern / PolarPattern (replicates Originals).
        if ftype in _TRANSFORM_OPS:
            op = doc.addObject(_KIND[ftype], fid)
            orig_names = params.get("_Originals") or []
            originals = [built_solids[n] for n in orig_names if n in built_solids]
            if not originals and built_solids:
                # Fall back to the most recently built solid.
                originals = [list(built_solids.values())[-1]]
            if not originals:
                report["recompute_errors"].append({"id": fid, "error": "no originals to pattern"})
                continue
            op.Originals = originals
            if isinstance(params.get("Occurrences"), (int, float)):
                op.Occurrences = int(params["Occurrences"])
            if ftype == "LinearPattern":
                if isinstance(params.get("Length"), (int, float)):
                    op.Length = float(params["Length"])
                ref, ref_prop = params.get("_Direction") or {}, "Direction"
            else:
                if isinstance(params.get("Angle"), (int, float)):
                    op.Angle = float(params["Angle"])
                ref, ref_prop = params.get("_Axis") or {}, "Axis"
            dir_obj = None
            if ref.get("is_sketch") and ref.get("object") in built_sketches:
                dir_obj = built_sketches[ref["object"]]
            elif ref.get("role"):
                dir_obj = _origin_axis(body, ref["role"])
            if dir_obj is not None:
                try:
                    setattr(op, ref_prop, (dir_obj, ref.get("subs", ["H_Axis"])))
                except Exception as e:  # noqa: BLE001
                    report["recompute_errors"].append({"id": fid, "error": f"set {ref_prop}: {e}"})
            if "Reversed" in params:
                op.Reversed = bool(params["Reversed"])
            body.addObject(op)
            doc.recompute()
            if op.State and "Invalid" in op.State:
                report["recompute_errors"].append({"id": fid, "error": "invalid after recompute"})
            else:
                report["built"].append({"id": fid, "type": ftype})
                built_solids[fid] = op
                have_solid = True
                try:
                    current_top = body.Shape.BoundBox.ZMax
                except Exception:
                    pass
            continue

        # Profile op: Pad / Pocket / Revolution / Groove / Hole
        prof_id = profile_of.get(fid)
        prof = built_sketches.get(prof_id)
        if prof is None:
            report["recompute_errors"].append({"id": fid, "error": "missing profile sketch"})
            continue
        op = doc.addObject(_KIND[ftype], fid)
        op.Profile = prof
        if ftype in ("Pad", "Pocket"):
            if isinstance(params.get("Length"), (int, float)):
                op.Length = float(params["Length"])
        elif ftype == "Hole":
            for prop in ("Diameter", "Depth", "DepthType", "DrillPoint",
                         "DrillPointAngle", "ThreadType", "Tapered"):
                if params.get(prop) is not None:
                    try:
                        setattr(op, prop, params[prop])
                    except Exception:
                        pass
        else:  # Revolution / Groove
            if isinstance(params.get("Angle"), (int, float)):
                op.Angle = float(params["Angle"])
            ax = params.get("_ReferenceAxis") or {}
            axis_obj = None
            if ax.get("role"):
                axis_obj = _origin_axis(body, ax["role"])
            elif ax.get("is_sketch") and ax.get("object") in built_sketches:
                axis_obj = built_sketches[ax["object"]]
            if axis_obj is not None:
                op.ReferenceAxis = (axis_obj, ax.get("subs", [""]))
            else:
                report["recompute_errors"].append({"id": fid, "error": "no reference axis"})
        if "Midplane" in params:
            op.Midplane = bool(params["Midplane"])
        if "Reversed" in params:
            op.Reversed = bool(params["Reversed"])
        body.addObject(op)
        doc.recompute()
        if op.State and "Invalid" in op.State:
            report["recompute_errors"].append({"id": fid, "error": "invalid after recompute"})
        else:
            report["built"].append({"id": fid, "type": ftype})
            built_solids[fid] = op
            have_solid = True
            try:
                current_top = body.Shape.BoundBox.ZMax
            except Exception:
                pass

    doc.recompute()
    report["doc_recomputed"] = not _has_errors(doc)
    report["final_object_count"] = len(doc.Objects)
    try:
        report["volume"] = round(float(body.Shape.Volume), 4)
    except Exception:
        report["volume"] = None
    return doc, report


def _has_errors(doc):
    for o in doc.Objects:
        st = getattr(o, "State", None)
        if st and ("Invalid" in st or "Error" in st):
            return True
    return False


def _roundtrip_compare(original_graph, rebuilt_doc):
    """Compare original graph vs re-extracted rebuilt doc (needs fcstd_parser)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fcstd_parser  # type: ignore

    re_raw = fcstd_parser.extract(rebuilt_doc)

    def kinds(g):
        return [f["type"] for f in g.get("features", []) if f["type"] not in ("Body",)]

    orig_seq = kinds(original_graph)
    re_seq = kinds(re_raw)
    _solid = ("Pad", "Pocket", "Revolution", "Groove")
    orig_solids = [t for t in orig_seq if t in _solid]
    re_solids = [t for t in re_seq if t in _solid]

    return {
        "orig_feature_seq": orig_seq,
        "rebuilt_feature_seq": re_seq,
        "solid_order_preserved": orig_solids == re_solids,
        "orig_sketch_count": sum(1 for t in orig_seq if t == "Sketch"),
        "rebuilt_sketch_count": sum(1 for t in re_seq if t == "Sketch"),
        "orig_solid_count": len(orig_solids),
        "rebuilt_solid_count": len(re_solids),
    }


def _original_volume(fcstd_path):
    od = App.openDocument(fcstd_path)
    try:
        bodies = [o for o in od.Objects if o.TypeId == "PartDesign::Body"]
        if bodies:
            return float(bodies[0].Shape.Volume)
        # fall back to any solid shape
        for o in od.Objects:
            sh = getattr(o, "Shape", None)
            if sh is not None and getattr(sh, "Volume", 0):
                return float(sh.Volume)
    finally:
        App.closeDocument(od.Name)
    return None


def process(graph, out_path, roundtrip=False, original_fcstd=None):
    doc, report = compile_graph(graph, os.path.splitext(os.path.basename(out_path))[0])
    report["source_id"] = graph.get("source_id", "")
    if roundtrip:
        try:
            rt = _roundtrip_compare(graph, doc)
        except Exception as e:  # noqa: BLE001
            rt = {"error": f"{type(e).__name__}: {e}"}
        if original_fcstd and os.path.exists(original_fcstd) and report.get("volume"):
            try:
                ov = _original_volume(original_fcstd)
                rt["original_volume"] = round(ov, 4) if ov else None
                rt["rebuilt_volume"] = report["volume"]
                rt["volume_match_pct"] = round(100 * report["volume"] / ov, 3) if ov else None
            except Exception as e:  # noqa: BLE001
                rt["volume_error"] = str(e)
        report["roundtrip"] = rt
    doc.saveAs(out_path)
    App.closeDocument(doc.Name)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph")
    ap.add_argument("--manifest")
    ap.add_argument("--out")
    ap.add_argument("--out-dir")
    ap.add_argument("--roundtrip", action="store_true")
    args = ap.parse_args()

    items = []
    if args.graph:
        g = json.load(open(args.graph, encoding="utf-8"))
        graph = g.get("feature_graph", g)
        items.append((graph, args.out or (os.path.splitext(args.graph)[0] + ".rebuilt.FCStd")))
    elif args.manifest:
        os.makedirs(args.out_dir, exist_ok=True)
        for entry in json.load(open(args.manifest, encoding="utf-8")):
            g = json.load(open(entry["graph"], encoding="utf-8"))
            graph = g.get("feature_graph", g)
            out = os.path.join(args.out_dir, entry["id"] + ".FCStd")
            items.append((graph, out, entry.get("original_fcstd")))
    else:
        ap.error("need --graph or --manifest")

    reports = []
    for item in items:
        graph, out = item[0], item[1]
        original = item[2] if len(item) > 2 else None
        rep = process(graph, out, roundtrip=args.roundtrip, original_fcstd=original)
        reports.append(rep)
        rt = rep.get("roundtrip", {})
        sys.stdout.write("REBUILT %s recompute=%s vol=%s unsupported=%d order_ok=%s\n" % (
            rep["source_id"], rep["doc_recomputed"], rep["volume"],
            len(rep["unsupported"]), rt.get("solid_order_preserved", "-")))
        sys.stdout.flush()

    if args.out_dir:
        json.dump(reports, open(os.path.join(args.out_dir, "_reports.json"), "w"), indent=2)
    elif args.out:
        json.dump(reports[0], open(args.out + ".report.json", "w"), indent=2)


if __name__ == "__main__":
    main()
