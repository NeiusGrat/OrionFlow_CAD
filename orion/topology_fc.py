"""Who built each face: FreeCAD-side topology extraction.

A built part arrives at the viewer as one merged mesh. Every face, edge and
vertex on it was produced by some feature of the Blueprint, but nothing carries
that fact across the export — so a user can look at a chamfer and the system
cannot say which feature made it, and neither can a repair loop.

This recovers the mapping, exactly, from FreeCAD's element map.

**Authorship, not lineage.** ``getElementHistory`` returns the whole ancestry of
an element, oldest last, and the naive readings of it are both wrong. The last
entry is a *sketch*. The first is whichever feature most recently touched the
shape, which for a fillet is the fillet even on faces it merely passed through.
A face's lineage genuinely runs back through its ancestors: the cylindrical face
of a fillet descends from the edge that was rounded, which descends from the pad
that made the edge.

The creator is the **earliest feature in that chain at which the element is
already a face** — before that point its ancestor was an edge, which is to say
it did not exist yet. On a pad → through-bore → fillet part this attributes the
bore wall to the bore, the rounded corner to the fillet, and the six flats to
the pad, which is what a person looking at the part would say.

With one further case, which is not an exception but the other half of the same
rule. A face a feature *created* has no entry in that feature's own element map
— the map records what an operation inherited, not what it minted. So an element
that resolves nowhere in its ancestry was made by the most recent operation in
it. Without this, every genuinely new face on a shelled or vented part came back
unattributed: 40 of 121 on the first enclosure measured.

**Feature ids come for free.** ``freecad/reconstruct.py`` creates every object
with ``addObject(kind, feature_id)``, so a FreeCAD object's ``Name`` is already
the Blueprint feature id. No matching is needed and none is done.

Runs inside FreeCAD's Python, in the process that just built the document —
there is no second kernel and no second tessellation. Imports nothing from
``app``; see ``app/services/topology.py`` for the consumer side.
"""

SCHEMA = "orionflow-topology-v1"

#: Features that add or remove material. A dressup (fillet, chamfer, draft,
#: thickness) is included because it authors faces of its own; a sketch and a
#: datum are not, because they author none.
SOLID_FEATURES = frozenset((
    "PartDesign::Pad", "PartDesign::Pocket",
    "PartDesign::Revolution", "PartDesign::Groove",
    "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft",
    "PartDesign::AdditivePipe", "PartDesign::SubtractivePipe",
    "PartDesign::AdditiveSphere", "PartDesign::SubtractiveSphere",
    "PartDesign::AdditiveBox", "PartDesign::AdditiveCylinder",
    "PartDesign::AdditiveCone", "PartDesign::AdditiveTorus",
    "PartDesign::Hole",
    "PartDesign::Fillet", "PartDesign::Chamfer",
    "PartDesign::Draft", "PartDesign::Thickness",
    "PartDesign::Mirrored", "PartDesign::LinearPattern",
    "PartDesign::PolarPattern", "PartDesign::MultiTransform",
))

#: A part with more topology than this is recorded up to the cap and marked
#: truncated. The sidecar is served on the request path; an unbounded one turns
#: a pathological model into a slow download for everybody.
MAX_FACES = 4000
MAX_EDGES = 12000
MAX_VERTICES = 12000

#: Millimetres. Coordinates are rounded before they are written so the sidecar
#: is stable byte-for-byte across rebuilds of identical geometry — a digest over
#: it is then meaningful.
NDIGITS = 6


def _r(x):
    return round(float(x), NDIGITS)


def _xyz(v):
    return [_r(v.x), _r(v.y), _r(v.z)]


def _surface_of(face):
    """Type name plus whatever parameters that type actually has.

    ``position`` is the surface's own anchor — a point on a cylinder's axis, a
    plane's origin — and is not the same as the face's centroid. The distinction
    matters downstream: a quarter-cylinder fillet face has a centroid out on the
    rounded surface, so measuring a pick against the centroid would miss the
    axis by the radius. Picking needs the anchor; display needs the centroid;
    both are recorded.
    """
    surf = face.Surface
    kind = type(surf).__name__
    info = {"surface": kind}
    # ``MajorRadius``/``MinorRadius`` are the toroid's, and it has no ``Radius``
    # at all. Omitting them left a torus with no parameters to measure against,
    # so picking on one silently fell back to its centroid — which for a blend
    # is several millimetres off the surface, and the tangent neighbour won.
    # A fillet meeting a fillet produces a toroid, so this is a common face.
    for attr, key in (("Radius", "radius"), ("Radius1", "radius1"),
                      ("Radius2", "radius2"), ("SemiAngle", "semi_angle"),
                      ("MajorRadius", "major_radius"),
                      ("MinorRadius", "minor_radius")):
        value = getattr(surf, attr, None)
        if isinstance(value, (int, float)):
            info[key] = _r(value)
    axis = getattr(surf, "Axis", None)
    if axis is not None:
        info["axis"] = _xyz(axis)
    for attr in ("Center", "Position", "Location"):
        anchor = getattr(surf, attr, None)
        if anchor is not None and hasattr(anchor, "x"):
            info["position"] = _xyz(anchor)
            break
    return info


def _normal_at_middle(face):
    """The outward normal at the face's parametric centre, or None.

    Orientation is deliberately NOT applied. It used to be, on the reasoning
    that OCC stores a face's natural normal plus a flag saying the solid uses
    it reversed — true of raw OCC, but FreeCAD's ``Face.normalAt`` has already
    applied that flag by the time we see the vector. Flipping it a second time
    turned it back inward.

    Measured rather than argued: step ``EPS`` off the face along each candidate
    and ask ``Shape.isInside``. Over four built parts, ``normalAt`` pointed
    outward on 34 of 34 faces and the orientation-applied vector on 13 — every
    ``Reversed`` face carried a normal pointing into the solid. That is most of
    a typical part, because PartDesign leaves the majority of a pad's faces
    reversed.
    """
    try:
        u0, u1, v0, v1 = face.ParameterRange
        return _xyz(face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0))
    except Exception:  # noqa: BLE001 - a degenerate face has no usable normal
        return None


def _bbox(shape):
    try:
        b = shape.BoundBox
        return [_r(b.XMin), _r(b.YMin), _r(b.ZMin),
                _r(b.XMax), _r(b.YMax), _r(b.ZMax)]
    except Exception:  # noqa: BLE001
        return None


class _Attribution:
    """Resolves ``FaceN``/``EdgeN``/``VertexN`` to the feature that created it.

    Built once per document because the reverse map and the build order are
    document-wide, and because falling back has to be decided once rather than
    per element.
    """

    def __init__(self, body, shape, order):
        self.body = body
        self.order = order
        self.rank = {name: i for i, name in enumerate(order)}
        self.reverse = {}
        self.element_maps = {}
        self.method = "element_map"

        try:
            self.reverse = dict(shape.ElementReverseMap)
        except Exception:  # noqa: BLE001
            self.reverse = {}
        if not self.reverse:
            # No element map: an older FreeCAD, or a shape that lost it through
            # an operation. Attribution is unavailable rather than guessed —
            # a wrong feature id is worse than an absent one, because the UI
            # would present it with the same confidence as a right one.
            self.method = "unavailable"

    def _map_of(self, obj):
        if obj.Name not in self.element_maps:
            try:
                self.element_maps[obj.Name] = dict(obj.Shape.ElementMap)
            except Exception:  # noqa: BLE001
                self.element_maps[obj.Name] = {}
        return self.element_maps[obj.Name]

    def of(self, element_name, prefix):
        """``(creator, lineage)`` for e.g. ``("Face3", "Face")``."""
        mapped = self.reverse.get(element_name)
        if not mapped:
            return None, []

        try:
            chain = self.body.getElementHistory(mapped)
        except Exception:  # noqa: BLE001
            return None, []

        creator, lineage = None, []
        newest = None
        for entry in chain:
            obj, mapped_here = entry[0], entry[1]
            name = getattr(obj, "Name", None)
            if not name or name == self.body.Name:
                continue
            if name not in lineage:
                lineage.append(name)
            if getattr(obj, "TypeId", "") not in SOLID_FEATURES:
                continue
            # The chain runs newest first, so the first solid feature in it is
            # the most recent operation this element passed through.
            if newest is None:
                newest = name
            # Already a face at this level means it existed here; earlier than
            # this its ancestor was an edge, and an edge is not the thing.
            if not self._map_of(obj).get(mapped_here, "").startswith(prefix):
                continue
            if creator is None or self.rank.get(name, 1 << 30) < self.rank.get(
                creator, 1 << 30
            ):
                creator = name

        # A face *created* by a feature has no entry in that feature's own
        # element map — the map records what it inherited, not what it minted.
        # So a bore wall, a vent wall, a shell's inner skin: every genuinely new
        # face resolves nowhere above, and the rule as first written left them
        # unattributed. They belong to the most recent operation in their
        # ancestry, which is the one that made them.
        #
        # This is not a guess standing in for a missing mechanism. It is the
        # remaining case of the same rule: existed-before means inherited,
        # exists-nowhere-before means created here.
        return (creator or newest), lineage


def _stable_ordinals(records):
    """Number each feature's own elements by geometry, not by OCC index.

    An OCC index is an address in one particular shape: rebuild the part with a
    hole moved and every index after it can shift, so a stored ``#f7`` silently
    comes to mean a different face. Sorting a feature's elements by position and
    size instead gives an ordinal that survives any rebuild which does not
    change that feature — which is the property a saved selection needs.

    Ties are possible (a symmetric part has genuinely interchangeable faces) and
    are broken by OCC index, so the numbering is at least deterministic.
    """
    by_feature = {}
    for rec in records:
        by_feature.setdefault(rec.get("feature"), []).append(rec)

    for feature, group in by_feature.items():
        group.sort(key=lambda r: (r.get("center") or [0, 0, 0],
                                  -(r.get("area") or r.get("length") or 0.0),
                                  r["index"]))
        for ordinal, rec in enumerate(group):
            if feature:
                rec["stable"] = "@%s.%s%d" % (feature, rec["_k"], ordinal)


def extract(doc, graph=None, occurrence="o1"):
    """Topology of the document's first PartDesign body, as plain data.

    Never raises: the caller is a build that has already succeeded, and a part
    whose topology could not be read is still a part the user can download.
    Failure is reported in the returned record as ``error``.
    """
    result = {
        "schema": SCHEMA,
        "occurrences": [],
        "faces": [], "edges": [], "vertices": [],
        "features": {},
        "counts": {},
        "attribution": "none",
        "truncated": [],
    }

    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if not bodies:
        result["error"] = "no PartDesign::Body in the document"
        return result
    body = bodies[0]
    shape = getattr(body, "Shape", None)
    if shape is None or shape.isNull():
        result["error"] = "the body has no shape"
        return result

    order = [o.Name for o in body.Group if o.TypeId in SOLID_FEATURES]
    attribution = _Attribution(body, shape, order)
    result["attribution"] = attribution.method

    shape_ref = "#%s.s1" % occurrence
    result["occurrences"] = [{
        "ref": "#%s" % occurrence,
        "name": body.Name,
        "label": body.Label,
        "shape": shape_ref,
        "bbox": _bbox(shape),
    }]

    def _record(items, prefix, kind_letter, limit, extra):
        out = []
        for i, item in enumerate(items):
            if i >= limit:
                result["truncated"].append(prefix.lower())
                break
            element = "%s%d" % (prefix, i + 1)
            creator, lineage = attribution.of(element, prefix)
            rec = {
                "ref": "%s.%s%d" % (shape_ref, kind_letter, i + 1),
                "index": i + 1,
                "element": element,
                "feature": creator,
                "lineage": lineage,
                "_k": kind_letter,
            }
            rec.update(extra(item))
            out.append(rec)
        return out

    def _face_extra(face):
        info = _surface_of(face)
        info["area"] = _r(face.Area)
        info["center"] = _xyz(face.CenterOfMass)
        info["normal"] = _normal_at_middle(face)
        info["bbox"] = _bbox(face)
        return info

    def _edge_extra(edge):
        info = {"curve": type(edge.Curve).__name__, "length": _r(edge.Length)}
        try:
            info["center"] = _xyz(edge.CenterOfMass)
        except Exception:  # noqa: BLE001 - a degenerate edge has no centroid
            info["center"] = None
        radius = getattr(edge.Curve, "Radius", None)
        if isinstance(radius, (int, float)):
            info["radius"] = _r(radius)
        verts = edge.Vertexes
        if len(verts) == 2:
            info["ends"] = [_xyz(verts[0].Point), _xyz(verts[1].Point)]
        return info

    def _vertex_extra(vertex):
        return {"center": _xyz(vertex.Point)}

    result["faces"] = _record(shape.Faces, "Face", "f", MAX_FACES, _face_extra)
    result["edges"] = _record(shape.Edges, "Edge", "e", MAX_EDGES, _edge_extra)
    result["vertices"] = _record(
        shape.Vertexes, "Vertex", "v", MAX_VERTICES, _vertex_extra)

    for group in (result["faces"], result["edges"], result["vertices"]):
        _stable_ordinals(group)
        for rec in group:
            rec.pop("_k", None)

    # The feature-first view. Derived rather than collected separately so it
    # cannot disagree with the per-element records it summarises.
    graph_ids = set()
    if graph:
        graph_ids = {f.get("id") for f in (graph.get("features") or []) if f.get("id")}

    for name in order:
        obj = doc.getObject(name)
        entry = {
            "type": getattr(obj, "TypeId", ""),
            "label": getattr(obj, "Label", name),
            "build_index": order.index(name),
            "faces": [], "edges": [], "vertices": [],
            # reconstruct.py names objects after Blueprint feature ids, but
            # FreeCAD sanitises and de-duplicates names. Say plainly whether
            # this one really is a Blueprint id rather than letting a caller
            # assume it.
            "blueprint_feature": name in graph_ids if graph_ids else None,
        }
        result["features"][name] = entry

    for key, group in (("faces", result["faces"]), ("edges", result["edges"]),
                       ("vertices", result["vertices"])):
        for rec in group:
            feature = rec.get("feature")
            if feature in result["features"]:
                result["features"][feature][key].append(rec["ref"])

    result["counts"] = {
        "occurrences": 1,
        "shapes": 1,
        "faces": len(result["faces"]),
        "edges": len(result["edges"]),
        "vertices": len(result["vertices"]),
        "features": len(result["features"]),
        "unattributed": sum(
            1 for r in result["faces"] if not r.get("feature")),
    }
    return result
