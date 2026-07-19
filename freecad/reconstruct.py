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
import Sketcher  # type: ignore

SUPPORTED = {"Body", "Sketch", "Pad", "Pocket", "Revolution", "Groove", "Hole",
             "Thickness", "LinearPattern", "PolarPattern", "Fillet", "Chamfer",
             "Loft", "Sweep", "Mirrored", "Draft"}
_KIND = {
    "Pad": "PartDesign::Pad",
    "Pocket": "PartDesign::Pocket",
    "Revolution": "PartDesign::Revolution",
    "Groove": "PartDesign::Groove",
    "Hole": "PartDesign::Hole",
    "LinearPattern": "PartDesign::LinearPattern",
    "PolarPattern": "PartDesign::PolarPattern",
    "Mirrored": "PartDesign::Mirrored",
    "Fillet": "PartDesign::Fillet",
    "Chamfer": "PartDesign::Chamfer",
    "Draft": "PartDesign::Draft",
    "Loft": "PartDesign::AdditiveLoft",     # Subtractive via parameters.Subtractive
    "Sweep": "PartDesign::AdditivePipe",
}
_PROFILE_OPS = {"Pad", "Pocket", "Revolution", "Groove", "Hole"}
_TRANSFORM_OPS = {"LinearPattern", "PolarPattern", "Mirrored"}
_DRESSUP_OPS = {"Fillet", "Chamfer"}


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


def _load_sibling(stem):
    """Load ``freecad/<stem>.py`` by absolute path.

    Same trick as orion_agent.addon.capabilities: FreeCAD ships its own
    lowercase ``freecad`` package, so a normal ``import freecad.<stem>``
    inside FreeCAD's interpreter would resolve against the wrong package.
    """
    import importlib.util

    name = "_orion_repo_%s" % stem
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), stem + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


_selgrammar = _load_sibling("edge_selectors")


def _parallel_to_axis(e, axis, tol=1e-5):
    """Two-vertex edge whose displacement is parallel to one axis."""
    vs = e.Vertexes
    if len(vs) != 2:
        return False
    a, b = vs[0].Point, vs[1].Point
    d = {"x": (a.x - b.x, a.y - b.y, a.z - b.z),
         "y": (a.y - b.y, a.x - b.x, a.z - b.z),
         "z": (a.z - b.z, a.x - b.x, a.y - b.y)}[axis]
    along, off1, off2 = d
    return abs(off1) <= tol and abs(off2) <= tol and abs(along) > tol


def _edge_convexity(shape, e):
    """Classify an edge as "convex", "concave" or "flat" by sampling.

    Orientation-free: 8 points on a small circle around the edge midpoint in
    the plane perpendicular to the tangent; the fraction inside the solid
    approximates the material's dihedral angle (a box edge encloses ~90 deg of
    material -> ~2/8 inside; a re-entrant pocket edge ~270 deg -> ~6/8).
    Smooth/seam edges land near 4/8 and classify as "flat" (never selected).
    """
    import math
    lo, hi = e.ParameterRange
    mid = (lo + hi) / 2.0
    p = e.valueAt(mid)
    t = e.tangentAt(mid)
    if t.Length < 1e-9:
        return "flat"
    t.normalize()
    ref = App.Vector(1, 0, 0) if abs(t.x) < 0.9 else App.Vector(0, 1, 0)
    u = t.cross(ref)
    u.normalize()
    v = t.cross(u)
    diag = shape.BoundBox.DiagonalLength or 1.0
    r = max(min(diag * 1e-3, 0.5), 1e-4)
    inside = 0
    for k in range(8):
        # 0.37 rad phase keeps samples off face-aligned directions.
        ang = 0.37 + k * math.pi / 4.0
        q = p + u * (r * math.cos(ang)) + v * (r * math.sin(ang))
        if shape.isInside(q, 1e-6, False):
            inside += 1
    if inside <= 3:
        return "convex"
    if inside >= 5:
        return "concave"
    return "flat"


def _edge_matches(shape, e, kind, arg, bb, tol):
    if kind == "all":
        return True
    if kind in ("top", "bottom", "z"):
        z = bb.ZMax if kind == "top" else bb.ZMin if kind == "bottom" else float(arg)
        ebb = e.BoundBox
        return ebb.ZMin >= z - tol and ebb.ZMax <= z + tol
    if kind == "horizontal":
        ebb = e.BoundBox
        return (ebb.ZMax - ebb.ZMin) <= tol
    if kind == "vertical":
        return _parallel_to_axis(e, "z", tol)
    if kind == "direction":
        return _parallel_to_axis(e, arg, tol)
    if kind == "circular":
        return type(e.Curve).__name__ == "Circle"
    if kind == "straight":
        return type(e.Curve).__name__ == "Line"
    if kind == "radius":
        return (type(e.Curve).__name__ == "Circle"
                and abs(e.Curve.Radius - float(arg)) <= max(0.01, 0.001 * float(arg)))
    if kind in ("convex", "concave"):
        return _edge_convexity(shape, e) == kind
    return False


def _select_edges(shape, selector, edge_type=None):
    """Resolve a semantic edge selector into FreeCAD edge names on ``shape``.

    Selectors are how an authored graph names edges without knowing FreeCAD's
    internal topology numbering. The grammar is shared with the harness's
    FeatureGraph validation via freecad/edge_selectors.py: keywords (all, top,
    bottom, vertical, horizontal, circular, straight, convex, concave),
    parameterized forms (direction:<x|y|z>, radius:<mm>, largest:<n>) and
    {"z": <mm>}. ``edge_type`` optionally filters by curve kind
    ("Line" / "Circle"). Deterministic for a given shape.
    """
    parsed = _selgrammar.parse(selector)
    if parsed is None:
        return []
    kind, arg = parsed
    tol = 1e-5
    bb = shape.BoundBox

    candidates = []
    for i, e in enumerate(shape.Edges):
        if edge_type:
            ct = type(e.Curve).__name__.replace("Geom", "")
            if not ct.startswith(edge_type):
                continue
        candidates.append((i, e))

    if kind == "largest":
        ranked = sorted(candidates, key=lambda ie: -ie[1].Length)[:int(arg)]
        return ["Edge%d" % (i + 1) for i, _ in sorted(ranked)]

    names = []
    for i, e in candidates:
        try:
            if _edge_matches(shape, e, kind, arg, bb, tol):
                names.append("Edge%d" % (i + 1))
        except Exception:  # noqa: BLE001 - a degenerate edge never aborts selection
            continue
    return names


def _select_faces(shape, selector):
    """Resolve a semantic face selector into FreeCAD face names on ``shape``.

    Vocabulary: all | vertical (planar side walls + walls of vertical
    cylinders) | horizontal | top | bottom. Used by Draft (faces to taper,
    neutral plane). Deterministic for a given shape.
    """
    sel = str(selector or "").strip().lower()
    if sel not in ("all", "vertical", "horizontal", "top", "bottom"):
        return []
    tol = 1e-5
    bb = shape.BoundBox
    names = []
    for i, f in enumerate(shape.Faces):
        try:
            stype = type(f.Surface).__name__
            if sel == "all":
                ok = True
            elif stype == "Plane":
                nz = abs(f.Surface.Axis.z)
                if sel == "vertical":
                    ok = nz <= tol
                elif sel == "horizontal":
                    ok = abs(nz - 1.0) <= tol
                elif sel == "top":
                    ok = abs(nz - 1.0) <= tol and f.BoundBox.ZMax >= bb.ZMax - tol
                else:  # bottom
                    ok = abs(nz - 1.0) <= tol and f.BoundBox.ZMin <= bb.ZMin + tol
            elif stype == "Cylinder" and sel == "vertical":
                ok = abs(abs(f.Surface.Axis.z) - 1.0) <= tol
            else:
                ok = False
            if ok:
                names.append("Face%d" % (i + 1))
        except Exception:  # noqa: BLE001 - a degenerate face never aborts selection
            continue
    return names


def _add_geometry(sketch, geom_list, constrain=False):
    """Add graph geometry to a sketch. With ``constrain=True`` every
    non-construction circle gets named driven dimensions (radius + center
    X/Y), keyed by the GRAPH index — ``r_geo3`` / ``x_geo3`` / ``y_geo3`` —
    so the parametrics pass can bind spreadsheet expressions to them and a
    human gets clickable dimensions when editing the sketch."""
    for g in geom_list:
        t = g.get("type")
        cons = bool(g.get("construction", False))
        try:
            if t == "Circle":
                c = App.Vector(g["cx"], g["cy"], 0)
                sketch.addGeometry(Part.Circle(c, App.Vector(0, 0, 1), g["radius"]), cons)
                if constrain and not cons:
                    gi = sketch.GeometryCount - 1
                    gname = g.get("index", gi)
                    for ctype, cname, val in (
                        ("Radius", f"r_geo{gname}", float(g["radius"])),
                        ("DistanceX", f"x_geo{gname}", float(g.get("cx", 0.0))),
                        ("DistanceY", f"y_geo{gname}", float(g.get("cy", 0.0))),
                    ):
                        try:
                            if ctype == "Radius":
                                ci = sketch.addConstraint(
                                    Sketcher.Constraint("Radius", gi, val))
                            else:
                                ci = sketch.addConstraint(
                                    Sketcher.Constraint(ctype, gi, 3, val))
                            sketch.renameConstraint(ci, cname)
                        except Exception as e:  # noqa: BLE001
                            sys.stderr.write(f"  constraint {cname} skipped: {e}\n")
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


def compile_graph(graph, doc_name="rebuilt", doc=None):
    """Build a FeatureGraph into a FreeCAD document. Returns (doc, report).

    Pass ``doc`` to compile into an existing (live) document — used by the
    agent bridge; FreeCAD auto-renames on name collisions and all internal
    wiring here is by object reference, so ids stay consistent.
    """
    report = {"unsupported": [], "recompute_errors": [], "built": []}
    if doc is None:
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
                if isinstance(sk.get("z"), (int, float)):
                    # Explicit height (loft sections, offset profiles).
                    z = float(sk["z"])
                else:
                    z = 0.0 if (not have_solid and plane in ("XY", "XZ", "YZ")) else current_top
                obj.Placement = _plane_placement(plane if plane in ("XY", "XZ", "YZ") else "XY", z)
            # Constrain only all-circle sketches: on mixed circle+spline
            # profiles (gears) the solver nudges geometry enough to fall off
            # gNucleus's 0.1% "matched" ramp (measured: mean 0.838 -> 0.802).
            geo = sk.get("geometry", [])
            all_circles = bool(geo) and all(
                e.get("type") == "Circle" for e in geo if not e.get("construction"))
            _add_geometry(obj, geo, constrain=all_circles)
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

        # Face dressup: Draft tapers selected faces (molding/casting release).
        if ftype == "Draft":
            base_ref = params.get("_Base") or {}
            base_obj = built_solids.get(base_ref.get("object"))
            if base_obj is None and built_solids:
                base_obj = list(built_solids.values())[-1]
            if base_obj is None:
                report["recompute_errors"].append({"id": fid, "error": "no base feature to draft"})
                continue
            faces = list(base_ref.get("faces") or [])
            if not faces:
                faces = _select_faces(base_obj.Shape, params.get("_Faces", "vertical"))
            if not faces:
                report["recompute_errors"].append(
                    {"id": fid, "error": "face selector matched no faces"})
                continue
            op = doc.addObject(_KIND[ftype], fid)
            op.Base = (base_obj, faces)
            if isinstance(params.get("Angle"), (int, float)):
                op.Angle = float(params["Angle"])
            neutral = _select_faces(base_obj.Shape,
                                    params.get("_NeutralPlane", "bottom"))
            if neutral:
                op.NeutralPlane = (base_obj, [neutral[0]])
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

        # Dressup: Fillet / Chamfer on edges of a prior feature. Edges come
        # either from an explicit extraction-time list (_Base.edges) or from a
        # semantic selector (_Edges) resolved against the base feature's shape.
        if ftype in _DRESSUP_OPS:
            base_ref = params.get("_Base") or {}
            base_obj = built_solids.get(base_ref.get("object"))
            if base_obj is None and built_solids:
                base_obj = list(built_solids.values())[-1]
            if base_obj is None:
                report["recompute_errors"].append({"id": fid, "error": "no base feature to dress up"})
                continue
            edges = list(base_ref.get("edges") or [])
            if not edges:
                edges = _select_edges(base_obj.Shape, params.get("_Edges", "all"),
                                      params.get("_EdgeType"))
            if not edges:
                report["recompute_errors"].append(
                    {"id": fid, "error": "edge selector matched no edges"})
                continue
            op = doc.addObject(_KIND[ftype], fid)
            op.Base = (base_obj, edges)
            if ftype == "Fillet" and isinstance(params.get("Radius"), (int, float)):
                op.Radius = float(params["Radius"])
            if ftype == "Chamfer" and isinstance(params.get("Size"), (int, float)):
                op.Size = float(params["Size"])
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
            if ftype == "Mirrored":
                # Mirror plane: a body origin plane by role (XY/XZ/YZ_Plane).
                role = str((params.get("_Plane") or {}).get("role", "YZ_Plane"))
                if not role.endswith("_Plane"):
                    role += "_Plane"
                plane_obj = _origin_axis(body, role)   # Origin holds planes too
                if plane_obj is None:
                    report["recompute_errors"].append(
                        {"id": fid, "error": "no mirror plane %s" % role})
                    doc.removeObject(op.Name)
                    continue
                op.MirrorPlane = (plane_obj, [""])
            else:
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

        # Multi-sketch solid ops: Loft (profile through section sketches) and
        # Sweep (profile along a spine path sketch). Additive by default;
        # parameters.Subtractive switches to the material-removing variant.
        if ftype in ("Loft", "Sweep"):
            prof = built_sketches.get(profile_of.get(fid))
            if prof is None:
                report["recompute_errors"].append({"id": fid, "error": "missing profile sketch"})
                continue
            subtractive = bool(params.get("Subtractive"))
            if ftype == "Loft":
                kind_id = ("PartDesign::SubtractiveLoft" if subtractive
                           else "PartDesign::AdditiveLoft")
            else:
                kind_id = ("PartDesign::SubtractivePipe" if subtractive
                           else "PartDesign::AdditivePipe")
            op = doc.addObject(kind_id, fid)
            op.Profile = prof
            if ftype == "Loft":
                secs = [built_sketches[str(s)] for s in (params.get("_Sections") or [])
                        if str(s) in built_sketches]
                if not secs:
                    report["recompute_errors"].append(
                        {"id": fid, "error": "Loft needs parameters._Sections "
                                             "(ids of already-built sketches)"})
                    doc.removeObject(op.Name)
                    continue
                op.Sections = secs
                if "Ruled" in params:
                    op.Ruled = bool(params["Ruled"])
                if "Closed" in params:
                    op.Closed = bool(params["Closed"])
            else:
                spine = built_sketches.get(str(params.get("_Spine", "")))
                if spine is None:
                    report["recompute_errors"].append(
                        {"id": fid, "error": "Sweep needs parameters._Spine "
                                             "(id of an already-built path sketch)"})
                    doc.removeObject(op.Name)
                    continue
                try:
                    op.Spine = spine
                except Exception:  # noqa: BLE001 - some versions want a sub list
                    op.Spine = (spine, [])
            body.addObject(op)
            doc.recompute()
            if op.State and "Invalid" in op.State:
                report["recompute_errors"].append({"id": fid, "error": "invalid after recompute"})
            else:
                report["built"].append({"id": fid, "type": ftype})
                built_solids[fid] = op
                if not subtractive:
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
    _apply_parametrics(doc, graph, built_sketches, built_solids, report)

    # GUI hygiene: headless documents carry no view state, so make the saved
    # file open clean — sketches hidden, only the finished solid showing.
    try:
        for sk_obj in built_sketches.values():
            sk_obj.Visibility = False
        if built_solids:
            for obj in built_solids.values():
                obj.Visibility = False
            list(built_solids.values())[-1].Visibility = True
    except Exception:  # noqa: BLE001 - cosmetic only
        pass
    return doc, report


def _apply_parametrics(doc, graph, built_sketches, built_solids, report):
    """Named-parameter layer: a ``Params`` spreadsheet whose aliased cells
    drive sketch constraints and feature lengths via expressions.

    Uses the graph's ``parameters`` section (name -> value -> bound_to targets
    recovered by parameter_mapper). Change ``outer_diameter`` in one cell and
    the whole part rebuilds. Fully rolled back if binding introduces any
    recompute error the document did not already have."""
    params = [p for p in graph.get("parameters", []) if p.get("bound_to")]
    if not params:
        return
    info = {"cells": 0, "expressions": 0, "skipped": [], "rolled_back": False}
    had_errors_before = _has_errors(doc)

    def _body_volume():
        try:
            body = next(o for o in doc.Objects
                        if o.TypeId == "PartDesign::Body")
            return float(body.Shape.Volume)
        except Exception:  # noqa: BLE001
            return None

    vol_before = _body_volume()

    sheet = doc.addObject("Spreadsheet::Sheet", "Params")
    for i, p in enumerate(params, start=1):
        try:
            sheet.set(f"A{i}", str(p["name"]))
            sheet.set(f"B{i}", str(p["value"]))
            sheet.setAlias(f"B{i}", str(p["name"]))
            info["cells"] += 1
        except Exception as e:  # noqa: BLE001
            info["skipped"].append(f"cell {p['name']}: {e}")
    doc.recompute()

    sketch_meta = {s["id"]: s for s in graph.get("sketches", [])}
    cnames = {sid: {c.Name for c in obj.Constraints if c.Name}
              for sid, obj in built_sketches.items()}
    applied, used = [], set()

    def _close(a, b):
        return abs(a - b) <= max(1e-4, 1e-3 * max(abs(a), abs(b)))

    def bind(obj, path, expr, key, expected=None):
        """Apply an expression only when the value it will drive matches the
        geometry that already exists — a mis-binding must never reshape the
        part. Records the original value so rollback can truly restore it."""
        if key in used:
            return
        if path.startswith("Constraints."):
            cname = path.split(".", 1)[1]
            current = float(obj.getDatum(cname).Value)
        else:
            current = float(getattr(obj, path))
        if expected is not None and not _close(expected, current):
            info["skipped"].append(
                f"{key}: nominal {expected:g} != modeled {current:g}")
            return
        obj.setExpression(path, expr)
        applied.append((obj, path, current))
        used.add(key)
        info["expressions"] += 1

    pad_len_param = None  # (name, master pad length) for through-cut coupling
    for p in params:
        name = str(p["name"])
        for b in p["bound_to"]:
            tgt, prop = b["target"], b["property"]
            try:
                pval = float(p["value"])
                if prop == "Length" and tgt in built_solids:
                    bind(built_solids[tgt], "Length", f"<<Params>>.{name}",
                         (tgt, "Length"), expected=pval)
                    feat = next((f for f in graph.get("features", [])
                                 if f["id"] == tgt), None)
                    if feat and feat.get("type") == "Pad":
                        pad_len_param = (name, pval)
                elif prop in ("Diameter", "Radius") and ":geo" in tgt:
                    sid, gidx = tgt.split(":geo")
                    cname = f"r_geo{gidx}"
                    if sid in built_sketches and cname in cnames.get(sid, ()):
                        if prop == "Diameter":
                            expr, expected = f"<<Params>>.{name} / 2", pval / 2
                        else:
                            expr, expected = f"<<Params>>.{name}", pval
                        bind(built_sketches[sid], f"Constraints.{cname}", expr,
                             (sid, cname), expected=expected)
                elif prop == "BoltCircleDiameter" and tgt in built_sketches:
                    import math as _m
                    for g in sketch_meta.get(tgt, {}).get("geometry", []):
                        if g.get("type") != "Circle":
                            continue
                        d = _m.hypot(g.get("cx", 0.0), g.get("cy", 0.0))
                        if d <= 1e-9:
                            continue
                        for ax, coeff in (("x", g["cx"] / (2 * d)),
                                          ("y", g["cy"] / (2 * d))):
                            cname = f"{ax}_geo{g['index']}"
                            if cname in cnames.get(tgt, ()):
                                bind(built_sketches[tgt],
                                     f"Constraints.{cname}",
                                     f"<<Params>>.{name} * {coeff:.10f}",
                                     (tgt, cname), expected=pval * coeff)
            except Exception as e:  # noqa: BLE001
                info["skipped"].append(f"{name}->{tgt}.{prop}: {e}")

    # Through-cut coupling: pockets cut at >=1.5x the pad depth stay through
    # when the thickness parameter changes.
    if pad_len_param:
        tname, pad_len = pad_len_param
        for f in graph.get("features", []):
            if f.get("type") != "Pocket" or f["id"] not in built_solids:
                continue
            if (f["id"], "Length") in used:
                continue
            try:
                if float(f["parameters"].get("Length", 0)) >= 1.5 * pad_len:
                    bind(built_solids[f["id"]], "Length",
                         f"<<Params>>.{tname} * 2", (f["id"], "Length"),
                         expected=2 * pad_len)
            except Exception as e:  # noqa: BLE001
                info["skipped"].append(f"through-cut {f['id']}: {e}")

    doc.recompute()
    vol_after = _body_volume()
    # The parametric layer must be a pure re-expression of the geometry that
    # already exists. Any volume shift means a binding forced a nominal spec
    # value onto the wrong (or a rounded) dimension — roll everything back;
    # a file without a Params sheet beats a file with wrong geometry.
    drifted = (
        vol_before is not None and vol_after is not None and vol_before > 0
        and abs(vol_after - vol_before) / vol_before > 0.001
    )
    if drifted or (_has_errors(doc) and not had_errors_before):
        for obj, path, original in applied:
            try:
                obj.setExpression(path, None)
                # Removing an expression keeps its last driven value —
                # restore the recorded original or the rollback is a lie.
                if path.startswith("Constraints."):
                    obj.setDatum(path.split(".", 1)[1], original)
                else:
                    setattr(obj, path, original)
            except Exception:  # noqa: BLE001
                pass
        try:
            doc.removeObject(sheet.Name)
        except Exception:  # noqa: BLE001
            pass
        doc.recompute()
        info["rolled_back"] = True
        if drifted:
            info["skipped"].append(
                f"volume drift {vol_before:.1f} -> {vol_after:.1f}")
    report["parametrics"] = info


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
