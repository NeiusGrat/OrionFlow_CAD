"""Reading the topology sidecar: selectors, lookup and picking.

``orion/topology_fc.py`` writes the record inside FreeCAD. Nothing here touches
OCC — this side runs in the API container, which has no kernel and must not
acquire one.

Two selector forms, because they answer different questions and conflating them
is the mistake this module exists to avoid.

``#o1.s1.f7`` — **an address in one built shape.** Occurrence, shape, then
element by OCC index. This is what a viewer has: it picked a triangle out of a
mesh and wants to know what it hit. It is exact and it is disposable. Rebuild
the part with a hole moved and every index after that hole can shift, so a
``#f7`` stored yesterday may name a different face today.

``@bore.f0`` — **a face of a named feature.** Anchored to the Blueprint feature
id and to an ordinal assigned by geometry rather than by OCC index, so it
survives any rebuild that does not change that feature. This is what a saved
selection, a repair instruction or an edit should hold.

Neither is a substitute for the Blueprint feature id itself, which is the only
identity that means anything across a redesign. The layering is deliberate:

    Blueprint feature id   survives a redesign
    @feature.f0            survives a rebuild
    #o1.s1.f7              addresses one artifact
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

#: Written beside the STEP and the GLB by the builder.
SIDECAR_NAME = "part.topology.json"

#: ``f`` face, ``e`` edge, ``v`` vertex — the letter in a selector.
KINDS = {"f": "faces", "e": "edges", "v": "vertices"}

_INDEXED = re.compile(
    r"^#(?:(?P<occ>o\d+)\.(?P<shape>s\d+)\.)?(?P<kind>[fev])(?P<index>\d+)$"
)
_STABLE = re.compile(
    r"^@(?P<feature>[A-Za-z_][A-Za-z0-9_]*)\.(?P<kind>[fev])(?P<ordinal>\d+)$"
)
_CONTAINER = re.compile(r"^#(?P<occ>o\d+)(?:\.(?P<shape>s\d+))?$")


class SelectorError(ValueError):
    """A selector that is not in the grammar. Distinguished from 'not found'."""


@dataclass(frozen=True)
class Selector:
    """A parsed selector. ``feature`` is set only for the ``@`` form."""

    form: str  # "indexed" | "stable" | "container"
    kind: Optional[str] = None  # "faces" | "edges" | "vertices"
    index: Optional[int] = None
    feature: Optional[str] = None
    ordinal: Optional[int] = None
    occurrence: str = "o1"
    shape: str = "s1"

    def __str__(self) -> str:
        if self.form == "stable":
            letter = next(k for k, v in KINDS.items() if v == self.kind)
            return f"@{self.feature}.{letter}{self.ordinal}"
        if self.form == "container":
            return f"#{self.occurrence}.{self.shape}"
        letter = next(k for k, v in KINDS.items() if v == self.kind)
        return f"#{self.occurrence}.{self.shape}.{letter}{self.index}"


def parse(selector: str) -> Selector:
    """Parse either selector form. Raises ``SelectorError`` on anything else.

    The shorthand ``#f7`` is accepted and means the sole occurrence and shape of
    a single-body part — which every part this system builds currently is. It
    expands to ``#o1.s1.f7`` on the way in, so a caller never has to special-case
    the day assemblies arrive.
    """
    text = (selector or "").strip()
    if not text:
        raise SelectorError("empty selector")

    m = _INDEXED.match(text)
    if m:
        return Selector(
            form="indexed",
            kind=KINDS[m.group("kind")],
            index=int(m.group("index")),
            occurrence=m.group("occ") or "o1",
            shape=m.group("shape") or "s1",
        )

    m = _STABLE.match(text)
    if m:
        return Selector(
            form="stable",
            kind=KINDS[m.group("kind")],
            feature=m.group("feature"),
            ordinal=int(m.group("ordinal")),
        )

    m = _CONTAINER.match(text)
    if m:
        return Selector(
            form="container",
            occurrence=m.group("occ"),
            shape=m.group("shape") or "s1",
        )

    raise SelectorError(
        f"{selector!r} is not a selector: expected #o1.s1.f7, #f7 or @feature.f0"
    )


def load(directory: str) -> Optional[dict[str, Any]]:
    """The sidecar for a build, or None when there is not a readable one.

    Takes a directory for the same reason ``artifacts.read_manifest`` does: the
    caller resolves which output base it means.
    """
    try:
        with open(os.path.join(directory, SIDECAR_NAME), encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def load_for_request(request_id: str) -> Optional[dict[str, Any]]:
    """The sidecar for a build, from disk or from object storage.

    Falls through to storage because per-request directories live on the
    container that built them, and on a scale-to-zero host that container is
    usually gone. A download can answer that with a redirect; this cannot — the
    record has to come back into the process to be queried.
    """
    from app.services import artifacts as artifact_paths

    record = load(os.path.join(artifact_paths.OUTPUT_BASE, request_id))
    if record is not None:
        return record

    from app.config import settings

    if not settings.is_s3_configured:
        return None

    from app.services.storage import get_storage

    blob = get_storage().fetch(artifact_paths.storage_key(request_id, SIDECAR_NAME))
    if not blob:
        return None
    try:
        record = json.loads(blob)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def elements(topology: dict, kind: str) -> list[dict]:
    value = topology.get(kind)
    return value if isinstance(value, list) else []


def resolve(topology: dict, selector: str | Selector) -> Optional[dict]:
    """The element a selector names, or None if this build has no such element.

    A parse failure raises; a lookup miss returns None. They are different
    answers — one means the caller asked wrongly, the other means the part
    changed — and a caller that cannot tell them apart will report a stale
    selection as a bug in the selector.
    """
    sel = parse(selector) if isinstance(selector, str) else selector

    if sel.form == "container":
        for occurrence in topology.get("occurrences") or []:
            if occurrence.get("ref") == f"#{sel.occurrence}":
                return occurrence
        return None

    if sel.form == "stable":
        wanted = str(sel)
        for rec in elements(topology, sel.kind):
            if rec.get("stable") == wanted:
                return rec
        return None

    for rec in elements(topology, sel.kind):
        if rec.get("index") == sel.index:
            return rec
    return None


def feature_of(topology: dict, selector: str | Selector) -> Optional[str]:
    """Which Blueprint feature authored the geometry this selector names."""
    rec = resolve(topology, selector)
    return rec.get("feature") if rec else None


def summary(topology: dict) -> dict[str, Any]:
    """Counts and the per-feature element tally, without the element records.

    The full sidecar for a dense part runs to megabytes. A client deciding what
    to render, or a person asking what a part is made of, needs this instead.
    """
    features = topology.get("features") or {}
    return {
        "schema": topology.get("schema"),
        "attribution": topology.get("attribution"),
        "counts": topology.get("counts") or {},
        "truncated": topology.get("truncated") or [],
        "occurrences": topology.get("occurrences") or [],
        "features": {
            name: {
                "type": entry.get("type"),
                "build_index": entry.get("build_index"),
                "blueprint_feature": entry.get("blueprint_feature"),
                "faces": len(entry.get("faces") or []),
                "edges": len(entry.get("edges") or []),
                "vertices": len(entry.get("vertices") or []),
            }
            for name, entry in features.items()
        },
    }


# --------------------------------------------------------------------------- #
# picking
# --------------------------------------------------------------------------- #
def _sub(a: Iterable[float], b: Iterable[float]) -> list[float]:
    return [x - y for x, y in zip(a, b)]


def _dot(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: Iterable[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def _within_bbox(point: list[float], bbox: Optional[list[float]], slack: float) -> bool:
    """A plane is infinite; the face cut from it is not.

    Without this the analytic distance to a large planar face would win for any
    point anywhere in its plane, including points off the end of the part.
    """
    if not bbox or len(bbox) != 6:
        return True
    return all(bbox[i] - slack <= point[i] <= bbox[i + 3] + slack for i in range(3))


def _surface_kind(face: dict) -> str:
    """``Plane``, ``Cylinder``, ... whatever prefix the record happens to carry.

    FreeCAD reports a surface as the bare class name (``Plane``) while its type
    id is ``Part::GeomPlane``; which one reaches the sidecar depends on how it
    was read. Comparing against one spelling silently matches nothing and every
    pick quietly degrades to a centroid distance — a wrong answer that still
    looks like an answer, which is why this normalises instead of assuming.
    """
    name = str(face.get("surface") or "")
    return name.rsplit("::", 1)[-1].replace("Geom", "", 1)


def _distance_to_face(point: list[float], face: dict) -> Optional[float]:
    """Analytic distance from a point to a face's surface, where we can.

    Exact for the surfaces this system actually produces — planes from pads and
    pockets, cylinders from bores and fillets, spheres — and falls back to the
    centroid for anything else, which is honest about being approximate rather
    than wrong about being exact.
    """
    kind = _surface_kind(face)
    centre = face.get("center")
    position = face.get("position")
    axis = face.get("axis")
    radius = face.get("radius")

    if kind == "Plane" and position and face.get("normal"):
        return abs(_dot(_sub(point, position), face["normal"]))

    if kind == "Cylinder" and position and axis and radius:
        offset = _sub(point, position)
        along = _dot(offset, axis)
        perpendicular = [offset[i] - along * axis[i] for i in range(3)]
        return abs(_norm(perpendicular) - radius)

    if kind == "Sphere" and position and radius:
        return abs(_norm(_sub(point, position)) - radius)

    if kind == "Toroid" and position and axis:
        major = face.get("major_radius")
        minor = face.get("minor_radius")
        if major is not None and minor is not None:
            # Distance to the tube: collapse to the generating circle of radius
            # ``major`` in the plane through ``position`` normal to ``axis``,
            # then measure against the tube radius.
            #
            # Worth the arithmetic because a toroid is where two fillets meet,
            # and it blends tangentially into both of its neighbours — a point
            # on it is microns from the adjoining cylinder. Without an exact
            # distance the neighbour always wins, which is what dropped rank-1
            # picking to 44.5% on a filleted enclosure.
            offset = _sub(point, position)
            along = _dot(offset, axis)
            perpendicular = [offset[i] - along * axis[i] for i in range(3)]
            radial = _norm(perpendicular) - major
            return abs(math.sqrt(radial * radial + along * along) - minor)

    if centre:
        return _norm(_sub(point, centre))
    return None


def pick(
    topology: dict,
    point: Iterable[float],
    kind: str = "faces",
    slack: float = 1.0,
    limit: int = 3,
) -> list[dict]:
    """Candidate elements at a 3D point, nearest first.

    This is what turns a click in the viewer into an engineering answer. The
    viewer raycasts the mesh it already has, gets a world-space hit, and asks
    here which face that was and which feature made it — no per-face GLB and no
    change to how the model is rendered.

    Returns candidates rather than one answer on purpose. A hit on the seam
    between two coplanar faces, or on the tangent line where a fillet meets the
    wall it blends into, is genuinely ambiguous at mesh resolution, and a caller
    that can see the runners-up can disambiguate with the surface normal it also
    has. Reporting a single face would be inventing a certainty the geometry
    does not have.
    """
    hit = [float(c) for c in point]
    scored = []
    for rec in elements(topology, kind):
        if not _within_bbox(hit, rec.get("bbox"), slack):
            continue
        distance = _distance_to_face(hit, rec)
        if distance is None:
            continue
        scored.append((distance, rec))

    scored.sort(key=lambda pair: (pair[0], pair[1].get("index", 0)))
    return [{**rec, "distance": round(distance, 6)} for distance, rec in scored[:limit]]
