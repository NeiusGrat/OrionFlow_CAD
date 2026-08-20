"""A read-only bridge over a *built artifact*, for the cloud studio.

The agent harness' geometry tools were written against
``orion_agent.harness.bridge_client.BridgeClient`` — an RPC channel into a live
FreeCAD desktop. That coupling is why the web product could only ever reach the
twelve knowledge tools: there is no FreeCAD in the API container and there is no
desktop on the other end of a browser session.

But a finished build already leaves behind everything those tools actually read.
``orion/topology_fc.py`` writes a sidecar with every face, edge and vertex — its
surface type, area, centroid, normal, bounding box, and which Blueprint feature
authored it — and the Blueprint itself resolves to the concrete FeatureGraph
without a kernel. So the tools do not need a document; they need *this*.

What this deliberately does **not** do is pretend to be a document. Anything
that would mutate geometry, recompute, render or open a file raises rather than
degrading: an edit belongs to ``/studio/rebuild`` and ``/editing``, which own
the freeze-build-verify contract. A tool that quietly did half an edit here
would produce a part nothing had graded.

Every number this returns is traceable to the sidecar or the Blueprint. Where a
quantity can only be estimated — the minimum distance between two curved faces,
for instance — it is returned with ``exact: false`` and the method named, and
the model is told so in the observation. An approximation presented as a
measurement is the failure mode this whole layer exists to prevent.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)

#: Faces/edges whose bounding boxes are within this many mm of touching are
#: treated as overlapping when deciding whether a plane-to-plane distance is
#: the true minimum. Sized against the sidecar's own rounding (4 decimals).
_OVERLAP_SLACK_MM = 1e-3

#: Two normals count as parallel when |cos| is within this of 1.
_PARALLEL_TOL = 1e-6


class PartBridgeError(RuntimeError):
    """A capability that only a live FreeCAD document can provide."""


def _kind_of(element: dict) -> str:
    """``vertex`` | ``planar`` | ``cylindrical`` | ``curve`` | ``other``."""
    ref = element.get("ref") or ""
    letter = ref.rsplit(".", 1)[-1][:1] if "." in ref else ""
    if letter == "v":
        return "vertex"
    if letter == "e":
        return "curve"
    surface = (element.get("surface") or "").lower()
    if "plane" in surface:
        return "planar"
    if "cylinder" in surface:
        return "cylindrical"
    return "other"


def _sub(a, b) -> list[float]:
    return [float(x) - float(y) for x, y in zip(a, b)]


def _dot(a, b) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _bbox_gap(p: Optional[list], q: Optional[list]) -> Optional[float]:
    """Minimum distance between two axis-aligned boxes — a true lower bound.

    Whatever the surfaces do between their extents, they cannot be closer than
    their boxes are. Reported as such rather than as the answer.
    """
    if not p or not q or len(p) != 6 or len(q) != 6:
        return None
    gaps = []
    for i in range(3):
        gaps.append(max(0.0, p[i] - q[i + 3], q[i] - p[i + 3]))
    return math.sqrt(sum(g * g for g in gaps))


def _boxes_overlap_off_axis(p: list, q: list, axis: int) -> bool:
    """Do two boxes overlap on the two axes that are not ``axis``?"""
    for i in range(3):
        if i == axis:
            continue
        if p[i] - q[i + 3] > _OVERLAP_SLACK_MM or q[i] - p[i + 3] > _OVERLAP_SLACK_MM:
            return False
    return True


def _dominant_axis(normal: Optional[list]) -> Optional[int]:
    """The axis a normal is aligned with, or None if it points off-axis."""
    if not normal or len(normal) != 3:
        return None
    for i in range(3):
        if abs(abs(float(normal[i])) - 1.0) < 1e-6:
            return i
    return None


def _point_in_box(point: list, box: Optional[list]) -> bool:
    if not box or len(box) != 6:
        return False
    return all(
        box[i] - _OVERLAP_SLACK_MM <= point[i] <= box[i + 3] + _OVERLAP_SLACK_MM
        for i in range(3)
    )


def _evaluate(expression: str, variables: dict) -> Any:
    """An expression's number, or None when it cannot be evaluated here.

    None rather than the expression string: a caller that cannot tell a value
    from its source would report ``"2*hole_r"`` as a dimension.
    """
    try:
        from orion import expr

        return expr.evaluate(expression, variables)
    except Exception:  # noqa: BLE001 — the expression is returned either way
        return None


def _measure_pair(a: dict, b: dict) -> dict:
    """Distance between two topology elements, with its method and its status.

    Exact where the sidecar's data determines the answer (vertex to vertex; a
    point against a planar face it projects onto; two parallel planar faces
    whose footprints overlap). Everything else returns the box gap as a proved
    lower bound plus the centroid separation, both flagged inexact.
    """
    ka, kb = _kind_of(a), _kind_of(b)
    ca, cb = a.get("center"), b.get("center")

    if ka == "vertex" and kb == "vertex" and ca and cb:
        return {
            "distance": round(_norm(_sub(ca, cb)), 6),
            "exact": True,
            "method": "vertex-to-vertex",
        }

    # A point against a plane: exact when the point projects inside the face.
    for point_el, face_el, flipped in ((a, b, False), (b, a, True)):
        if _kind_of(point_el) == "vertex" and _kind_of(face_el) == "planar":
            p, c, n = point_el.get("center"), face_el.get("center"), face_el.get("normal")
            if p and c and n and abs(_norm(n) - 1.0) < 1e-3:
                signed = _dot(_sub(p, c), n)
                foot = [p[i] - signed * float(n[i]) for i in range(3)]
                inside = _point_in_box(foot, face_el.get("bbox"))
                return {
                    "distance": round(abs(signed), 6),
                    "exact": bool(inside),
                    "method": "point-to-plane"
                    + ("" if inside else " (the point projects outside the face)"),
                    "flipped": flipped,
                }

    # Two parallel planes: exact when their footprints overlap, because then
    # the shortest path between them runs along the shared normal.
    if ka == "planar" and kb == "planar":
        na, nb = a.get("normal"), b.get("normal")
        if na and nb and abs(abs(_dot(na, nb)) - 1.0) < _PARALLEL_TOL and ca and cb:
            gap = abs(_dot(_sub(cb, ca), na))
            axis = _dominant_axis(na)
            overlap = (
                axis is not None
                and a.get("bbox")
                and b.get("bbox")
                and _boxes_overlap_off_axis(a["bbox"], b["bbox"], axis)
            )
            return {
                "distance": round(gap, 6),
                "exact": bool(overlap),
                "method": "plane-to-parallel-plane"
                + ("" if overlap else " (footprints do not overlap)"),
            }

    lower = _bbox_gap(a.get("bbox"), b.get("bbox"))
    centroid = round(_norm(_sub(ca, cb)), 6) if ca and cb else None
    return {
        "distance": lower if lower is not None else centroid,
        "exact": False,
        "method": f"bounding-box lower bound ({ka} to {kb})",
        "lower_bound": lower,
        "centroid_distance": centroid,
    }


class PartBridge:
    """The read half of a bridge, served from a build's artifacts.

    ``part`` is the studio's bundle for the open part (blueprint, stats,
    verification); ``request_id`` addresses its topology sidecar. Either may be
    absent — the tools then say what is missing rather than guessing.
    """

    def __init__(self, request_id: str = "", part: Optional[dict] = None):
        self.request_id = (request_id or "").strip()
        self.part = part or {}
        self._topology: Optional[dict] = None
        self._topology_loaded = False
        self._graph: Optional[dict] = None
        self._graph_tried = False

    # -- sources ------------------------------------------------------- #
    def topology(self) -> Optional[dict]:
        """The sidecar for this build, loaded once."""
        if not self._topology_loaded:
            self._topology_loaded = True
            if self.request_id:
                from app.services import topology as topo

                try:
                    self._topology = topo.load_for_request(self.request_id)
                except Exception as exc:  # noqa: BLE001 — a tool says so instead
                    logger.warning("part_bridge_topology_failed", error=str(exc))
                    self._topology = None
        return self._topology

    def graph(self) -> Optional[dict]:
        """The Blueprint resolved to a concrete FeatureGraph, loaded once.

        Not re-frozen: the stored payload already carries its hash, and running
        the static checker again at read time could refuse a part the user
        already owns because a rule was added since it was built.
        """
        if not self._graph_tried:
            self._graph_tried = True
            blueprint = self.part.get("blueprint")
            if isinstance(blueprint, dict) and blueprint.get("template"):
                try:
                    from orion.blueprint import Blueprint

                    graph = Blueprint.from_dict(blueprint).resolve()
                    graph.pop("_analysis", None)
                    self._graph = graph
                except Exception as exc:  # noqa: BLE001
                    logger.warning("part_bridge_resolve_failed", error=repr(exc))
                    self._graph = None
        return self._graph

    def _require_topology(self) -> dict:
        record = self.topology()
        if record is None:
            raise PartBridgeError(
                "this part has no topology record on file, so its faces, edges "
                "and vertices cannot be inspected — answer from the Blueprint "
                "and the verification report instead"
            )
        return record

    # -- bridge surface (read only) ------------------------------------ #
    def list_objects(self) -> dict:
        record = self._require_topology()
        objects = []
        for occurrence in record.get("occurrences") or []:
            objects.append(
                {
                    "name": occurrence.get("name") or "Body",
                    "type_id": "PartDesign::Body",
                    "parametric": True,
                    "faces": (record.get("counts") or {}).get("faces", 0),
                }
            )
        for name, entry in (record.get("features") or {}).items():
            objects.append(
                {
                    "name": name,
                    "type_id": entry.get("type") or "",
                    "parametric": True,
                    "faces": len(entry.get("faces") or []),
                }
            )
        return {"objects": objects}

    def inspect_topology(self, name: Optional[str] = None) -> dict:
        """The whole body, or one feature's contribution to it.

        Shaped as ``{"shapes": [...]}`` because that is what
        ``orion_agent.harness.topology`` serialises — same summariser as the
        desktop path, so a claim reads identically wherever it was made.
        """
        record = self._require_topology()
        shapes = [self._body_shape(record)]
        for feature in (record.get("features") or {}):
            shapes.append(self._feature_shape(record, feature))
        if name:
            wanted = [s for s in shapes if s.get("name") == name or s.get("label") == name]
            if not wanted:
                raise PartBridgeError(
                    f"no object named {name!r} in this build; it has: "
                    + ", ".join(s.get("name", "?") for s in shapes)
                )
            shapes = wanted
        return {"shapes": shapes, "request_id": self.request_id}

    def get_object_parameters(self, name: str) -> dict:
        """A feature's parameters — resolved value *and* authoring expression.

        Both, deliberately. The resolved number is what the kernel built with;
        the expression is where it came from. Handing the model only the number
        loses the one fact that distinguishes a derived dimension from an
        invented one.
        """
        graph = self.graph()
        if graph is None:
            raise PartBridgeError(
                "this part carries no resolvable Blueprint, so its feature "
                "parameters cannot be read"
            )
        resolved = {f.get("id"): f for f in graph.get("features") or []}
        if name not in resolved:
            raise PartBridgeError(
                f"no feature named {name!r}; this part has: "
                + ", ".join(k for k in resolved if k)
            )

        # A sketch's dimensions do not live in its feature parameters — they
        # live in the profile builder that generated its geometry. Returning
        # the empty parameter dict was true and useless: it says a sketch has
        # no dimensions, when in fact it has all of them.
        if (resolved[name].get("type") or "") == "Sketch":
            return self._sketch_parameters(name, graph)

        template = {
            f.get("id"): (f.get("parameters") or {})
            for f in ((self.part.get("blueprint") or {}).get("template") or {}).get(
                "features"
            )
            or []
        }
        expressions = template.get(name, {})
        parameters: dict[str, Any] = {}
        for key, value in (resolved[name].get("parameters") or {}).items():
            source = expressions.get(key)
            if isinstance(source, str) and source != value and not key.startswith("_"):
                parameters[key] = {"value": value, "expression": source}
            else:
                parameters[key] = value
        return {
            "name": name,
            "type": resolved[name].get("type"),
            "parameters": parameters,
            "variables": (self.part.get("blueprint") or {}).get("variables") or {},
        }

    def _sketch_parameters(self, name: str, graph: dict) -> dict:
        """A sketch's real dimensions: its plane, its builder and its arguments.

        Resolved values beside the expressions that produced them, same as a
        solid feature — a bore diameter is a number in the profile args, and
        that is where a question about it has to be answered.
        """
        template = (self.part.get("blueprint") or {}).get("template") or {}
        authored = next(
            (s for s in template.get("sketches") or [] if s.get("id") == name), {}
        )
        built = next(
            (s for s in graph.get("sketches") or [] if s.get("id") == name), {}
        )
        spec = authored.get("profile") or {}
        expressions = spec.get("args") or {}
        variables = (self.part.get("blueprint") or {}).get("variables") or {}
        parameters: dict[str, Any] = {
            "profile_builder": spec.get("builder"),
            "plane": built.get("plane") or authored.get("plane"),
        }
        for key, value in expressions.items():
            if isinstance(value, str):
                parameters[key] = {
                    "value": _evaluate(value, variables),
                    "expression": value,
                }
            else:
                parameters[key] = value
        if "z" in built:
            parameters["z"] = built["z"]
        geometry = built.get("geometry") or []
        kinds: dict[str, int] = {}
        for item in geometry:
            kind = item.get("type", "?")
            kinds[kind] = kinds.get(kind, 0) + 1
        parameters["geometry"] = kinds
        return {
            "name": name,
            "type": "Sketch",
            "parameters": parameters,
            "variables": (self.part.get("blueprint") or {}).get("variables") or {},
        }

    def measure(self, a: dict, b: dict) -> dict:
        record = self._require_topology()
        ea = self._element(record, a)
        eb = self._element(record, b)
        result = _measure_pair(ea, eb)
        result["a"] = ea.get("ref") or ea.get("element")
        result["b"] = eb.get("ref") or eb.get("element")
        result["a_feature"] = ea.get("feature")
        result["b_feature"] = eb.get("feature")
        return result

    def extract_featuregraph(self) -> dict:
        graph = self.graph()
        if graph is None:
            raise PartBridgeError(
                "this part carries no resolvable Blueprint, so no FeatureGraph "
                "can be extracted"
            )
        return {"graph": graph}

    def get_model_tier(self) -> dict:
        """Tier A whenever a Blueprint resolves — source travels with the shape.

        Not a courtesy: the tier decides which edit path is legal, and a part
        built from a frozen Blueprint really is code-native, however it is
        being viewed.
        """
        if self.graph() is not None:
            return {
                "tier": "A",
                "rationale": "built from a frozen Blueprint; the source template "
                "and its variables are on file, so edits go through resolve and "
                "rebuild rather than through B-rep surgery",
            }
        if self.topology() is not None:
            return {
                "tier": "B",
                "rationale": "a feature history exists in the topology record, "
                "but no Blueprint template was supplied with this part",
            }
        return {"tier": "unknown", "rationale": "no build artifacts are on file"}

    # -- shaping ------------------------------------------------------- #
    def _body_shape(self, record: dict) -> dict:
        counts = record.get("counts") or {}
        occurrences = record.get("occurrences") or []
        name = (occurrences[0].get("name") if occurrences else None) or "Body"
        bbox = occurrences[0].get("bbox") if occurrences else None
        stats = self.part.get("stats") or {}
        shape = {
            "name": name,
            "label": (occurrences[0].get("label") if occurrences else name) or name,
            "solids": stats.get("solids"),
            "faces": counts.get("faces"),
            "edges": counts.get("edges"),
            "vertices": counts.get("vertices"),
            "surface_types": self._tally(record.get("faces") or [], "surface"),
            "curve_types": self._tally(record.get("edges") or [], "curve"),
            "cylindrical_faces": sum(
                1
                for f in record.get("faces") or []
                if "cylinder" in (f.get("surface") or "").lower()
            ),
            "bounding_box": self._bbox_dict(bbox),
        }
        if stats.get("volume_mm3"):
            shape["volume"] = stats["volume_mm3"]
        return shape

    def _feature_shape(self, record: dict, feature: str) -> dict:
        entry = (record.get("features") or {}).get(feature) or {}
        faces = [f for f in record.get("faces") or [] if f.get("feature") == feature]
        edges = [e for e in record.get("edges") or [] if e.get("feature") == feature]
        verts = [v for v in record.get("vertices") or [] if v.get("feature") == feature]
        return {
            "name": feature,
            "label": entry.get("label") or feature,
            "solids": None,
            "faces": len(entry.get("faces") or faces),
            "edges": len(entry.get("edges") or edges),
            "vertices": len(entry.get("vertices") or verts),
            "surface_types": self._tally(faces, "surface"),
            "curve_types": self._tally(edges, "curve"),
            "cylindrical_faces": sum(
                1 for f in faces if "cylinder" in (f.get("surface") or "").lower()
            ),
            "bounding_box": self._bbox_dict(self._union_bbox(faces)),
        }

    @staticmethod
    def _tally(records: list[dict], key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for rec in records:
            value = rec.get(key)
            if value:
                out[value] = out.get(value, 0) + 1
        return out

    @staticmethod
    def _union_bbox(records: list[dict]) -> Optional[list[float]]:
        boxes = [r.get("bbox") for r in records if r.get("bbox") and len(r["bbox"]) == 6]
        if not boxes:
            return None
        return [min(b[i] for b in boxes) for i in range(3)] + [
            max(b[i + 3] for b in boxes) for i in range(3)
        ]

    @staticmethod
    def _bbox_dict(bbox: Optional[list]) -> dict:
        if not bbox or len(bbox) != 6:
            return {}
        return {
            "min": [round(bbox[i], 4) for i in range(3)],
            "max": [round(bbox[i + 3], 4) for i in range(3)],
            "size": [round(bbox[i + 3] - bbox[i], 4) for i in range(3)],
        }

    @staticmethod
    def _element(record: dict, ref: Any) -> dict:
        """Resolve ``{name, sub}``, a selector string, or a bare element name.

        The model is given three vocabularies elsewhere in the product — OCC
        element names, indexed selectors and stable ``@feature.f0`` selectors —
        so it is accepted in all three here rather than being corrected for
        using the one it happened to see last.
        """
        from app.services import topology as topo

        if isinstance(ref, str):
            token = ref.strip()
        elif isinstance(ref, dict):
            token = str(ref.get("sub") or ref.get("selector") or ref.get("name") or "").strip()
        else:
            token = ""
        if not token:
            raise PartBridgeError(
                "a measurement needs both ends named, e.g. {'sub': 'Face3'} or "
                "{'sub': '@bore.f0'}"
            )

        if token.startswith(("#", "@")):
            found = topo.resolve(record, token)
            if found is None:
                raise PartBridgeError(f"{token!r} names nothing in this build")
            return found

        for kind in ("faces", "edges", "vertices"):
            for rec in topo.elements(record, kind):
                if rec.get("element") == token:
                    return rec
        raise PartBridgeError(
            f"{token!r} names nothing in this build — use an element name like "
            "'Face3', an index selector like '#f3', or a stable selector like "
            "'@bore.f0'"
        )

    # -- everything else ----------------------------------------------- #
    def __getattr__(self, name: str):
        """Refuse the write half loudly.

        A tool that reached for ``set_parameter`` here would be trying to edit a
        document that does not exist. Failing with the reason is the only honest
        answer; returning a plausible success would put an ungraded change in
        front of the user.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        def _refuse(*_args, **_kwargs):
            raise PartBridgeError(
                f"'{name}' needs a live FreeCAD document. This part is a "
                "finished build: it can be inspected and measured, but changing "
                "it goes through a rebuild, not through a tool call."
            )

        return _refuse


def for_part(request_id: str = "", part: Optional[dict] = None) -> Optional[PartBridge]:
    """A bridge for the open part, or None when there is nothing to inspect."""
    if not request_id and not (part or {}).get("blueprint"):
        return None
    return PartBridge(request_id=request_id, part=part)
