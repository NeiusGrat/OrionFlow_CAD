"""Asking a built part which feature made a piece of it.

The viewer renders one merged mesh. A user clicking a chamfer on it is asking an
engineering question — *what made this?* — and until now the system had no way
to answer, because the mapping from geometry to feature exists only inside the
FreeCAD document and died with the container that built it.

``orion/topology_fc.py`` now records it at build time. These routes read it back.

``POST /resolve`` is the one that matters. A viewer raycasts the mesh it already
has, gets a world-space point, and posts it; the answer names the face, the
Blueprint feature that authored it, and the lineage behind it. Nothing about how
the model is rendered has to change — no per-face GLB, no second mesh, no
client-side topology.

Selectors are POSTed rather than put in the path because they begin with ``#``
or ``@``: a ``#`` in a URL is a fragment and never reaches the server.
"""

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import topology as topo
from app.services.artifacts import is_safe_request_id

router = APIRouter(tags=["Topology"])


class ResolveRequest(BaseModel):
    """One of ``selector``, ``point`` or ``feature``. Exactly one."""

    selector: Optional[str] = Field(
        default=None,
        description="`#o1.s1.f7`, the shorthand `#f7`, or the stable `@bore.f0`",
        examples=["#f7", "@bore.f0"],
    )
    point: Optional[list[float]] = Field(
        default=None,
        description="World-space XYZ of a pick, in millimetres",
        examples=[[5.0, 0.0, 5.0]],
    )
    feature: Optional[str] = Field(
        default=None, description="A Blueprint feature id, e.g. `bore`"
    )
    kind: Literal["faces", "edges", "vertices"] = "faces"
    limit: int = Field(default=3, ge=1, le=25)


def _load(request_id: str) -> dict[str, Any]:
    if not is_safe_request_id(request_id):
        raise HTTPException(400, "Invalid request ID")
    record = topo.load_for_request(request_id)
    if record is None:
        raise HTTPException(404, "No topology recorded for this build")
    if record.get("error"):
        # The build succeeded and the extraction did not. Say which, rather
        # than reporting the part as having no topology.
        raise HTTPException(422, f"Topology unavailable: {record['error']}")
    return record


@router.get("/{request_id}")
async def get_summary(request_id: str):
    """Counts and the per-feature tally, without the element records.

    The full sidecar for a dense part runs to megabytes; this is what a client
    deciding what to render actually needs. The whole record is downloadable at
    ``/api/v1/artifacts/{request_id}/part.topology.json`` for a caller that
    wants it.
    """
    return topo.summary(_load(request_id))


@router.get("/{request_id}/features/{feature}")
async def get_feature(request_id: str, feature: str):
    """Everything one Blueprint feature authored — the highlight query.

    Returns the element records, not just their refs, so a client can outline a
    feature without a request per face.
    """
    record = _load(request_id)
    entry = (record.get("features") or {}).get(feature)
    if entry is None:
        known = sorted((record.get("features") or {}).keys())
        raise HTTPException(
            404, f"No feature {feature!r} in this build; it has {known}"
        )

    refs = {kind: set(entry.get(kind) or []) for kind in ("faces", "edges", "vertices")}
    return {
        "feature": feature,
        "type": entry.get("type"),
        "build_index": entry.get("build_index"),
        "blueprint_feature": entry.get("blueprint_feature"),
        **{
            kind: [r for r in topo.elements(record, kind) if r["ref"] in refs[kind]]
            for kind in ("faces", "edges", "vertices")
        },
    }


@router.post("/{request_id}/resolve")
async def resolve(request_id: str, body: ResolveRequest):
    """Turn a selector, a pick point or a feature id into geometry and authorship.

    A pick returns ranked candidates rather than one answer. A hit on the seam
    between coplanar faces, or on the tangent where a fillet meets the wall it
    blends into, is genuinely ambiguous at mesh resolution; a caller holding the
    runners-up can disambiguate with the surface normal it already has, whereas
    a single face would be a certainty the geometry does not support.
    """
    given = [k for k in ("selector", "point", "feature") if getattr(body, k)]
    if len(given) != 1:
        raise HTTPException(400, "Provide exactly one of selector, point or feature")

    record = _load(request_id)

    if body.selector:
        try:
            selector = topo.parse(body.selector)
        except topo.SelectorError as exc:
            raise HTTPException(400, str(exc)) from exc
        element = topo.resolve(record, selector)
        if element is None:
            # Not a bad selector — a selector this build has nothing for. Most
            # often a stale `#f7` held across a rebuild, which is exactly what
            # the `@feature.f0` form exists to avoid.
            raise HTTPException(404, f"{selector} names nothing in this build")
        return {"query": str(selector), "match": element}

    if body.feature:
        return await get_feature(request_id, body.feature)

    if len(body.point) != 3:
        raise HTTPException(400, "point must be [x, y, z]")
    return {
        "query": {"point": body.point, "kind": body.kind},
        "candidates": topo.pick(record, body.point, kind=body.kind, limit=body.limit),
    }
