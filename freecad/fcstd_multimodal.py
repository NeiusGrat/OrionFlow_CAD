"""Multimodal FCStd extractor (4-layer GNN training tensors).

RUNS UNDER FREECAD'S PYTHON ONLY. Extends the base ``fcstd_parser`` raw graph
with the four layers OrionFlow's GNN needs to learn spatial + topological intent:

    Layer 1  GNN structure   : one-hot op tokens, normalized param vectors,
                               chronological index, InList/Support/Expression edges
    Layer 2  Spatial physics : per-step BoundBox, CenterOfMass, volumetric delta
    Layer 3  Sketch math     : geometry sub-graph, constraint matrix (tokenized), DoF
    Layer 4  TNP healing     : face IDs replaced by CenterOfMass + Normal + adjacency

Usage (FreeCAD python.exe, NOT freecadcmd which eats ``--`` flags):
    python.exe fcstd_multimodal.py --fcstd part.FCStd --id part --out dir/
"""

import argparse
import json
import os
import sys

import FreeCAD as App  # type: ignore

# Reuse the proven base extractor (same directory).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fcstd_parser as base  # noqa: E402

SCHEMA_VERSION = "ofl_fcstd_multimodal_v1"

# Fixed operation vocabulary -> one-hot index (stable across the dataset).
OP_VOCAB = [
    "Body", "Sketch", "Pad", "Pocket", "Revolution", "Groove",
    "Fillet", "Chamfer", "Hole", "Thickness",
    "LinearPattern", "PolarPattern", "Mirrored", "Other",
]
OP_INDEX = {name: i for i, name in enumerate(OP_VOCAB)}

# Constraint token map (Layer 3 constraint matrix).
CONSTRAINT_TOKEN = {
    "Coincident": 1, "Horizontal": 2, "Vertical": 3,
    "Distance": 4, "DistanceX": 5, "DistanceY": 6,
    "Radius": 7, "Diameter": 8, "Equal": 9, "Parallel": 10,
    "Perpendicular": 11, "Tangent": 12, "Symmetric": 13,
    "Angle": 14, "PointOnObject": 15, "Block": 16,
}

SOLID_TYPES = {
    "PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution",
    "PartDesign::Groove", "PartDesign::Fillet", "PartDesign::Chamfer",
    "PartDesign::Hole", "PartDesign::Thickness", "PartDesign::LinearPattern",
    "PartDesign::PolarPattern", "PartDesign::Mirrored",
}


def _op_token(short_type):
    idx = OP_INDEX.get(short_type, OP_INDEX["Other"])
    vec = [0] * len(OP_VOCAB)
    vec[idx] = 1
    return {"index": idx, "name": OP_VOCAB[idx], "one_hot": vec}


def _param_vector(params):
    """Flatten a feature's editable params into named numeric channels.

    Booleans -> 0/1, enums -> kept as label (not numeric), numbers passthrough.
    The GNN consumes ``numeric`` (already a flat float list); ``named`` keeps
    provenance for debugging / inverse mapping.
    """
    named, numeric = {}, []
    for k, v in params.items():
        if k.startswith("_"):
            continue  # structural refs (e.g. _ReferenceAxis) handled as edges
        if isinstance(v, bool):
            named[k] = float(v)
            numeric.append(float(v))
        elif isinstance(v, (int, float)):
            named[k] = float(v)
            numeric.append(float(v))
        else:
            named[k] = v  # enum string (e.g. "Length")
    return {"named": named, "numeric": numeric}


def _face_anchor(face):
    """Stable geometric identity for a face: COM + outward normal + extent."""
    try:
        com = face.CenterOfMass
        u, v = face.Surface.parameter(com)
        n = face.normalAt(u, v)
        if str(face.Orientation) == "Reversed":
            n = n.negative()
        return {
            "center_of_mass": [round(com.x, 6), round(com.y, 6), round(com.z, 6)],
            "normal": [round(n.x, 6), round(n.y, 6), round(n.z, 6)],
            "area": round(float(face.Area), 6),
        }
    except Exception:
        return None


def _adjacency_normals(shape, target_face):
    """Normals of faces sharing an edge with ``target_face`` (TNP adjacency)."""
    out = []
    try:
        tcom = target_face.CenterOfMass
        for f in shape.Faces:
            if f.isSame(target_face):
                continue
            shares = False
            for e in f.Edges:
                for te in target_face.Edges:
                    if e.isSame(te):
                        shares = True
                        break
                if shares:
                    break
            if shares:
                a = _face_anchor(f)
                if a:
                    out.append(a["normal"])
    except Exception:
        pass
    return out


def _center_of_mass(sh):
    """Centroid of any shape. Solids expose ``CenterOfMass``; Compounds (which
    Pocket/Pattern booleans return) do not, so aggregate their solids volume-
    weighted, falling back to the bounding-box center."""
    com = getattr(sh, "CenterOfMass", None)
    if com is not None:
        return com
    solids = getattr(sh, "Solids", None) or []
    if solids:
        tot = 0.0
        sx = sy = sz = 0.0
        for s in solids:
            v = float(s.Volume)
            c = s.CenterOfMass
            sx += c.x * v
            sy += c.y * v
            sz += c.z * v
            tot += v
        if tot:
            return App.Vector(sx / tot, sy / tot, sz / tot)
    bb = sh.BoundBox
    return App.Vector(bb.Center.x, bb.Center.y, bb.Center.z)


def _spatial_timeline(kept):
    """Layer 2: rolling BoundBox / CoM / volumetric delta along the feature tree.

    PartDesign stores each feature's *cumulative* body shape in ``feature.Shape``,
    so we read state directly per step (no Tip rollback needed) and diff volumes
    against the previous solid step to label additive vs subtractive operations.
    """
    timeline = []
    prev = {"vol": 0.0, "area": 0.0, "nf": 0, "ne": 0, "nv": 0}
    for o in kept:
        if o.TypeId not in SOLID_TYPES:
            continue
        try:
            sh = o.Shape
            bb = sh.BoundBox
            com = _center_of_mass(sh)
            vol = float(sh.Volume)
            area = float(sh.Area)
            nf, ne, nv = len(sh.Faces), len(sh.Edges), len(sh.Vertexes)
        except Exception:
            continue
        delta = round(vol - prev["vol"], 6)
        timeline.append({
            "feature": o.Name,
            "type": base._short_type(o.TypeId),
            "bbox6": [round(bb.XMin, 6), round(bb.YMin, 6), round(bb.ZMin, 6),
                      round(bb.XMax, 6), round(bb.YMax, 6), round(bb.ZMax, 6)],
            "center_of_mass": [round(com.x, 6), round(com.y, 6), round(com.z, 6)],
            "volume": round(vol, 6),
            "surface_area": round(area, 6),
            "face_count": nf, "edge_count": ne, "vertex_count": nv,
            "valid": bool(sh.isValid()),
            "closed": bool(sh.isClosed()),
            "solid_count": len(sh.Solids),
            "volume_delta": delta,
            "area_delta": round(area - prev["area"], 6),
            "face_delta": nf - prev["nf"],
            "edge_delta": ne - prev["ne"],
            "vertex_delta": nv - prev["nv"],
            "additive": delta >= 0,
        })
        prev = {"vol": vol, "area": area, "nf": nf, "ne": ne, "nv": nv}
    return timeline


def _sketch_dof(sk):
    """Degrees of freedom; 0 == fully constrained (weight heavily in loss)."""
    try:
        sk.recompute()
    except Exception:
        pass
    for getter in ("getDoFs", "getDoF"):
        fn = getattr(sk, getter, None)
        if callable(fn):
            try:
                return int(fn())
            except Exception:
                continue
    # Fallback: solver-reported state.
    try:
        return int(sk.solve())
    except Exception:
        return None


def _final_topology(kept, max_faces=2000):
    """Stable topology descriptors for the FINAL solid (anti-TNP foundation).

    Scoped to the final solid (not every timeline step) and guarded by
    ``max_faces`` so complex parts don't explode the JSON. Faces/edges carry
    geometric descriptors + adjacency so references survive topological renaming.
    """
    target = None
    for o in reversed(kept):
        if o.TypeId not in SOLID_TYPES:
            continue
        try:
            if o.Shape and o.Shape.Solids:
                target = o
                break
        except Exception:
            continue
    if target is None:
        return None
    sh = target.Shape
    faces = sh.Faces
    if len(faces) > max_faces:
        return {"source_feature": target.Name, "face_count": len(faces),
                "edge_count": len(sh.Edges), "vertex_count": len(sh.Vertexes),
                "skipped": "exceeds max_faces", "faces": [], "edges": []}

    # Map shared-edge hash -> face indices for O(F+E) adjacency.
    edge_faces = {}
    for fi, f in enumerate(faces):
        for e in f.Edges:
            try:
                edge_faces.setdefault(e.hashCode(), set()).add(fi)
            except Exception:
                continue
    face_recs = []
    for fi, f in enumerate(faces):
        adj = set()
        for e in f.Edges:
            try:
                adj |= edge_faces.get(e.hashCode(), set())
            except Exception:
                continue
        adj.discard(fi)
        rec = {"index": fi, "surface_type": type(f.Surface).__name__,
               "area": round(float(f.Area), 6), "edge_count": len(f.Edges),
               "adjacent_faces": sorted(adj)}
        a = _face_anchor(f)
        if a:
            rec["center_of_mass"] = a["center_of_mass"]
            rec["normal"] = a["normal"]
        face_recs.append(rec)

    edge_recs = []
    for ei, e in enumerate(sh.Edges):
        try:
            c = e.CenterOfMass
            rec = {"index": ei, "curve_type": type(e.Curve).__name__,
                   "length": round(float(e.Length), 6),
                   "center": [round(c.x, 6), round(c.y, 6), round(c.z, 6)]}
            vs = e.Vertexes
            if len(vs) >= 2:
                d = vs[-1].Point - vs[0].Point
                if d.Length > 1e-9:
                    d = d / d.Length
                    rec["direction"] = [round(d.x, 6), round(d.y, 6), round(d.z, 6)]
            edge_recs.append(rec)
        except Exception:
            continue

    return {"source_feature": target.Name, "face_count": len(faces),
            "edge_count": len(sh.Edges), "vertex_count": len(sh.Vertexes),
            "faces": face_recs, "edges": edge_recs}


def _tnp_anchors(doc_objs, kept_names):
    """Layer 4: replace 'Face3'-style refs with geometric coordinate vectors.

    Covers (a) sketches mapped onto a support face and (b) dress-up features
    (Fillet/Chamfer) whose Base references specific faces/edges.
    """
    anchors = []
    for o in doc_objs:
        # (a) face-attached sketches
        if o.TypeId == "Sketcher::SketchObject":
            sup = getattr(o, "AttachmentSupport", None) or getattr(o, "Support", None)
            if not sup:
                continue
            try:
                ref_obj, subs = sup[0][0], list(sup[0][1])
            except Exception:
                continue
            for sub in subs or []:
                if not sub.startswith("Face"):
                    continue
                try:
                    face = ref_obj.Shape.getElement(sub)
                except Exception:
                    continue
                a = _face_anchor(face)
                if a:
                    anchors.append({
                        "feature": o.Name, "relation": "sketch_on_face",
                        "raw_ref": "%s.%s" % (ref_obj.Name, sub),
                        "target": a,
                        "adjacency_normals": _adjacency_normals(ref_obj.Shape, face),
                    })
        # (b) dress-up features referencing faces/edges
        base_prop = getattr(o, "Base", None)
        if base_prop and o.TypeId in (
            "PartDesign::Fillet", "PartDesign::Chamfer", "PartDesign::Thickness",
        ):
            try:
                ref_obj, subs = base_prop[0], list(base_prop[1])
            except Exception:
                continue
            for sub in subs or []:
                try:
                    elem = ref_obj.Shape.getElement(sub)
                except Exception:
                    continue
                com = getattr(elem, "CenterOfMass", None)
                rec = {"feature": o.Name, "relation": "dressup_on_%s" % sub[:4].lower(),
                       "raw_ref": "%s.%s" % (ref_obj.Name, sub)}
                if com is not None:
                    rec["target_center_of_mass"] = [round(com.x, 6), round(com.y, 6), round(com.z, 6)]
                if sub.startswith("Face"):
                    a = _face_anchor(elem)
                    if a:
                        rec["target"] = a
                        rec["adjacency_normals"] = _adjacency_normals(ref_obj.Shape, elem)
                anchors.append(rec)
    return anchors


def _topo_edges(kept, kept_names):
    """Layer 1 edges beyond profile/base: Support + Expression links."""
    edges = []
    for o in kept:
        # Support / AttachmentSupport (what a feature physically stands on)
        for prop in ("Support", "AttachmentSupport"):
            sup = getattr(o, prop, None)
            if not sup:
                continue
            try:
                src = sup[0][0]
                if src is not None and src.Name in kept_names and src.Name != o.Name:
                    edges.append({"source": src.Name, "target": o.Name,
                                  "kind": "support"})
            except Exception:
                pass
        # Expression links (Spreadsheet.Width -> Pad.Length): design intent.
        try:
            ee = o.ExpressionEngine or []
        except Exception:
            ee = []
        for entry in ee:
            try:
                prop_path, expr = str(entry[0]), str(entry[1])
            except Exception:
                continue
            for other in kept:
                if other.Name != o.Name and other.Name in expr:
                    edges.append({"source": other.Name, "target": o.Name,
                                  "kind": "expression", "property": prop_path,
                                  "expression": expr})
    return edges


def _sketch_subgraphs(raw, kept):
    """Layer 3 sub-graphs: geometry + tokenized constraint matrix + DoF.

    Built as a standalone block (does not mutate ``raw['sketches']``) so the
    feature_graph stays within its strict schema while the GNN still gets the
    constraint math + the fully-constrained signal to weight in its loss."""
    sk_by_name = {o.Name: o for o in kept if o.TypeId == "Sketcher::SketchObject"}
    out = []
    for sk in raw.get("sketches", []):
        obj = sk_by_name.get(sk["id"])
        dof = _sketch_dof(obj) if obj else None
        matrix = [{"index": c.get("index"), "type": c["type"],
                   "token": CONSTRAINT_TOKEN.get(c["type"], 0),
                   "value": c.get("value")} for c in sk.get("constraints", [])]
        out.append({
            "id": sk["id"],
            "plane": sk.get("plane"),
            "dof": dof,
            "fully_constrained": (dof == 0) if dof is not None else None,
            "geometry": sk.get("geometry", []),
            "external_geometry": sk.get("external_geometry", []),
            "constraint_matrix": matrix,
        })
    return out


def extract_multimodal(doc):
    """Base raw graph + the four GNN layers.

    The multimodal block is built defensively: if enrichment fails on an exotic
    part, the row still yields a valid base ``feature_graph`` (with the failure
    recorded) instead of dropping the sample from the dataset."""
    raw = base.extract(doc)
    try:
        raw["multimodal"] = _build_multimodal(doc, raw)
    except Exception as e:  # noqa: BLE001
        raw["multimodal"] = {"error": "%s: %s" % (type(e).__name__, e)}
    raw["schema_version"] = SCHEMA_VERSION
    return raw


def _build_multimodal(doc, raw):
    kept = [o for o in doc.Objects if o.TypeId not in base.BOILERPLATE_TYPES]
    kept_names = {o.Name for o in kept}
    n = len(kept)

    # --- Layer 1: GNN nodes -------------------------------------------------
    node_index = {o.Name: i for i, o in enumerate(kept)}
    nodes = []
    for i, o in enumerate(kept):
        st = base._short_type(o.TypeId)
        nodes.append({
            "node_id": i,
            "id": o.Name,
            "op_token": _op_token(st),
            "param_vector": _param_vector(base._feature_params(o)),
            "chrono_index": round(i / max(n - 1, 1), 6),
        })

    # --- Layer 1: edges (profile/base from raw + support/expression) --------
    extra_edges = _topo_edges(kept, kept_names)
    all_edges = list(raw["dependencies"]) + extra_edges
    edge_index = [[node_index[e["source"]], node_index[e["target"]]]
                  for e in all_edges
                  if e["source"] in node_index and e["target"] in node_index]
    edge_attr = [e.get("kind", "base") for e in all_edges
                 if e["source"] in node_index and e["target"] in node_index]

    # --- Layers 2 & 4: read solid shapes FIRST. These need every feature's
    # cumulative .Shape intact, so they must run before any per-object
    # recompute (e.g. sketch DoF solve) dirties downstream features. ----------
    spatial_timeline = _spatial_timeline(kept)
    tnp_anchors = _tnp_anchors(doc.Objects, kept_names)
    final_topology = _final_topology(kept)

    # --- Layer 3: sketch sub-graphs (kept OUT of the schema-validated graph;
    # the shared raw["sketches"] stay untouched so feature_graph validates). ---
    sketch_subgraphs = _sketch_subgraphs(raw, kept)

    return {
        "op_vocab": OP_VOCAB,
        "constraint_token_map": CONSTRAINT_TOKEN,
        "nodes": nodes,
        "edge_index": edge_index,
        "edge_attr": edge_attr,
        "spatial_timeline": spatial_timeline,
        "sketch_subgraphs": sketch_subgraphs,
        "tnp_anchors": tnp_anchors,
        "final_topology": final_topology,
    }


def parse_file(fcstd_path, source_id):
    doc = App.openDocument(fcstd_path)
    try:
        doc.recompute()
        out = extract_multimodal(doc)
        out["source_id"] = source_id
        return out
    finally:
        App.closeDocument(doc.Name)


def _emit(item, out_dir):
    sid, path = item["id"], item["fcstd"]
    out_path = os.path.join(out_dir, sid + ".multimodal.json")
    try:
        data = parse_file(path, sid)
        json.dump(data, open(out_path, "w", encoding="utf-8"), indent=2)
        mm = data["multimodal"]
        sys.stdout.write(
            "OK %s nodes=%d edges=%d steps=%d tnp=%d\n" % (
                sid, len(mm["nodes"]), len(mm["edge_index"]),
                len(mm["spatial_timeline"]), len(mm["tnp_anchors"])))
        return True
    except Exception as e:  # noqa: BLE001
        json.dump({"source_id": sid, "error": "%s: %s" % (type(e).__name__, e)},
                  open(out_path, "w", encoding="utf-8"), indent=2)
        sys.stdout.write("ERR %s %s\n" % (sid, e))
        return False
    finally:
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", help="JSON list of {id, fcstd}")
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
        if _emit(it, args.out):
            ok += 1
        else:
            err += 1
    sys.stdout.write("DONE ok=%d err=%d\n" % (ok, err))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
