"""Click a face, change the thing that made it.

The round trip these routes complete::

    click            a point in the viewer
    → inspect        which feature authored that face, and what it can change
    → plan           what setting a dimension would do, and what else moves
    → commit         retune, rebuild, re-grade against the same contract

``inspect`` and ``plan`` build nothing and cost nothing, which is what lets the
UI call them on hover and on every drag of a slider. Only ``commit`` reaches the
kernel, and it is metered exactly like ``/studio/rebuild`` because it *is* a
rebuild — the same FreeCAD container, the same cost.

Targeting accepts a point, a selector or a feature id. The first two resolve
through the topology sidecar, which is why they need the ``request_id`` of the
build being looked at: a selector is an address in one particular artifact. A
feature id needs nothing, because it is the identity that outlives the artifact.

Nothing here can change the template. That is deliberate and it is the whole
guarantee: a retune moves values, the assertions are expressions over those same
values, so the rebuilt part is graded against the contract it was designed to.
Adding a feature is a different act with a different honesty requirement, and it
lives in ``/studio/rebuild`` with ``contract_broken`` attached.
"""

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.logging_config import get_logger
from app.services.studio_persistence import StudioGate, studio_gate

logger = get_logger(__name__)
router = APIRouter(tags=["Editing"])


class Target(BaseModel):
    """Where the user pointed. Exactly one of these."""

    feature: Optional[str] = Field(
        default=None, description="A Blueprint feature id — needs no build"
    )
    selector: Optional[str] = Field(
        default=None, description="`#f11` or `@bore.f0`; needs `request_id`"
    )
    point: Optional[list[float]] = Field(
        default=None, description="World-space XYZ of a click; needs `request_id`"
    )


class InspectRequest(BaseModel):
    blueprint: dict[str, Any]
    target: Target
    #: The build being looked at. Required for point and selector targeting.
    request_id: Optional[str] = None


class PlanRequest(InspectRequest):
    parameter: str
    value: float


class CommitRequest(PlanRequest):
    pass


class AddRequest(BaseModel):
    """Apply a CAD operation to geometry the user pointed at."""

    blueprint: dict[str, Any]
    #: `Chamfer`, `Fillet`, `Draft`, `Thickness` — see GET /operations.
    operation: str
    target: Target
    #: The numbers the operation's dialog collected, keyed by parameter name.
    dimensions: dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = None


def _resolve_target(target: Target, request_id: Optional[str]) -> tuple[str, dict]:
    """``(feature_id, evidence)`` — how the click became a feature.

    The evidence travels back so the UI can show *why* a panel opened on this
    feature. A pick is a ranked guess against a mesh; presenting its result with
    no provenance would make an inference look like a fact.
    """
    given = [k for k in ("feature", "selector", "point") if getattr(target, k)]
    if len(given) != 1:
        raise HTTPException(400, "Provide exactly one of feature, selector or point")

    if target.feature:
        return target.feature, {"via": "feature"}

    if not request_id:
        raise HTTPException(
            400, "request_id is required to resolve a point or a selector"
        )

    from app.services import topology as topo
    from app.services.artifacts import is_safe_request_id

    if not is_safe_request_id(request_id):
        raise HTTPException(400, "Invalid request ID")
    record = topo.load_for_request(request_id)
    if record is None:
        raise HTTPException(404, "No topology recorded for that build")

    if target.selector:
        try:
            selector = topo.parse(target.selector)
        except topo.SelectorError as exc:
            raise HTTPException(400, str(exc)) from exc
        element = topo.resolve(record, selector)
        if element is None:
            raise HTTPException(404, f"{selector} names nothing in that build")
        feature = element.get("feature")
        if not feature:
            raise HTTPException(422, f"{selector} could not be attributed to a feature")
        return feature, {"via": "selector", "element": element}

    if len(target.point) != 3:
        raise HTTPException(400, "point must be [x, y, z]")
    candidates = topo.pick(record, target.point, limit=3)
    attributed = [c for c in candidates if c.get("feature")]
    if not attributed:
        raise HTTPException(404, "Nothing at that point could be attributed")
    best = attributed[0]
    return best["feature"], {
        "via": "point",
        "element": best,
        # The runners-up travel too: a hit on a tangent seam is genuinely
        # ambiguous, and a UI that can offer "did you mean the fillet?" is
        # better than one that silently picks for the user.
        "other_candidates": [
            {"ref": c["ref"], "feature": c.get("feature"), "distance": c["distance"]}
            for c in attributed[1:]
        ],
    }


def _refuse(exc: Exception) -> HTTPException:
    """An edit rejected before the kernel is a 400, never a failed build."""
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail={"error": str(exc)})


@router.post("/inspect")
def inspect(request: InspectRequest):
    """What did I click, and what can I change about it?

    Free: no model call, no kernel, no meter. The UI opens its panel from this.
    """
    from app.services import semantic_edit

    feature, evidence = _resolve_target(request.target, request.request_id)
    try:
        parameters = semantic_edit.editable(request.blueprint, feature)
    except semantic_edit.EditError as exc:
        raise _refuse(exc) from exc

    return {
        "feature": feature,
        "resolved": evidence,
        "parameters": [p.as_dict() for p in parameters],
        # A feature whose dimensions are all computed is real and common — a
        # mirrored or patterned feature owns no numbers of its own. Saying so
        # explicitly stops the UI rendering an empty panel as an error.
        "editable": any(p.direct for p in parameters),
    }


@router.post("/plan")
def plan_edit(request: PlanRequest):
    """What would this change do? Builds nothing.

    Cheap enough to call on every frame of a slider drag, which is the point:
    the user sees what else moves *before* committing, rather than discovering
    it in the rebuilt geometry.
    """
    from app.services import semantic_edit

    feature, evidence = _resolve_target(request.target, request.request_id)
    try:
        edit = semantic_edit.plan(
            request.blueprint, feature, request.parameter, request.value
        )
    except semantic_edit.EditError as exc:
        raise _refuse(exc) from exc

    return {"resolved": evidence, "plan": edit.as_dict()}


@router.get("/operations")
def operations():
    """What the workbench can apply, and what it cannot apply yet.

    The planned list travels with its reason. A tool that is simply absent
    reads as an oversight; one that says it needs a profile sketched on the
    face is a roadmap the user can plan around.
    """
    from app.services import direct_edit

    return direct_edit.catalogue()


def _picked_element(request: "AddRequest") -> dict:
    """The edge or face record the operation will be applied to.

    A direct edit needs a specific piece of geometry, so a feature id is not
    enough to target one — refused here rather than silently dressing whatever
    the class selector happens to match.
    """
    if request.target.feature and not (request.target.selector or request.target.point):
        raise HTTPException(
            400,
            "select an edge or a face — a feature id does not say which one "
            "the operation applies to",
        )
    _feature, evidence = _resolve_target(request.target, request.request_id)
    element = evidence.get("element")
    if not element:
        raise HTTPException(422, "that selection resolved to no geometry")
    return element


@router.post("/add/plan")
def plan_add(request: AddRequest):
    """What would adding this feature do? Builds nothing.

    Reports ``contract_broken`` before the kernel runs, so the UI can warn that
    the verdict about to be shown grades a design the model never authored.
    """
    from app.services import direct_edit

    element = _picked_element(request)
    try:
        operation = direct_edit.plan(
            request.blueprint, request.operation, element, request.dimensions
        )
    except direct_edit.DirectEditError as exc:
        raise _refuse(exc) from exc

    return {"element": element, "operation": operation.as_dict()}


@router.post("/add/commit")
def commit_add(
    request: AddRequest,
    background: BackgroundTasks,
    gate: StudioGate = Depends(studio_gate),
):
    """Add the feature and rebuild. Metered — this one runs the kernel.

    The response always reports ``contract_broken: true``. That is not a
    failure; it is the honest consequence of changing the template, and the UI
    must stop presenting the verdict as a grade of *this* part.
    """
    from app.api.v1.studio import _feature_tree_for, _record_when_finished
    from app.services import blueprint_edit, blueprint_service, direct_edit

    if not gate.known:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "sign in to edit this part",
                "reason": "authentication_required",
            },
        )
    if not gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": gate.message or "monthly generation limit reached",
                "reason": gate.reason,
                "used": gate.used,
                "limit": gate.limit,
            },
        )

    element = _picked_element(request)
    try:
        operation = direct_edit.plan(
            request.blueprint, request.operation, element, request.dimensions
        )
        edited = direct_edit.apply(request.blueprint, operation)
    except (direct_edit.DirectEditError, blueprint_edit.EditError) as exc:
        raise _refuse(exc) from exc

    bundle = blueprint_service.build_from_payload(edited)

    background.add_task(
        _record_when_finished,
        {"bundle": bundle},
        f"{request.operation.lower()}: {operation.label}",
        gate.user_id,
    )

    # A build that produced a solid is not the same as a build that applied the
    # operation. A failed dressup leaves the previous geometry standing, so the
    # volume is unchanged and every assertion still passes — reporting that as
    # success tells the user their edit worked when nothing happened.
    not_applied = direct_edit.build_failure(
        bundle, direct_edit.added_feature_id(edited)
    )

    return {
        "success": bool(bundle.get("success")) and not not_applied,
        "not_applied": not_applied,
        "operation": operation.as_dict(),
        "element": element,
        "part_class": bundle.get("part_class", ""),
        "variables": bundle.get("variables", {}),
        "blueprint": bundle.get("blueprint"),
        "feature_tree": _feature_tree_for(bundle),
        "files": bundle.get("files", {}),
        "topology": bundle.get("topology") or {},
        "stats": bundle.get("stats"),
        "verification": bundle.get("verification") or {},
        "contract_broken": blueprint_edit.template_changed(request.blueprint, edited),
        "generation_time_ms": bundle.get("generation_time_ms", 0),
        "request_id": bundle.get("request_id", ""),
        "error": bundle.get("error") or not_applied,
    }


@router.post("/commit")
def commit_edit(
    request: CommitRequest,
    background: BackgroundTasks,
    gate: StudioGate = Depends(studio_gate),
):
    """Apply the edit and rebuild. Metered — this one runs the kernel.

    The response carries the plan beside the result on purpose. "What I asked
    for" and "what came out" are different claims, and a user changing a bore
    from 5 mm to 7 mm should be able to see both without a second request.
    """
    from app.services import blueprint_edit, blueprint_service, semantic_edit
    from app.api.v1.studio import _feature_tree_for, _record_when_finished

    if not gate.known:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "sign in to edit this part",
                "reason": "authentication_required",
            },
        )
    if not gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": gate.message or "monthly generation limit reached",
                "reason": gate.reason,
                "used": gate.used,
                "limit": gate.limit,
            },
        )

    feature, evidence = _resolve_target(request.target, request.request_id)
    try:
        edit = semantic_edit.plan(
            request.blueprint, feature, request.parameter, request.value
        )
        edited = semantic_edit.apply(request.blueprint, edit)
    except semantic_edit.EditError as exc:
        raise _refuse(exc) from exc

    bundle = blueprint_service.build_from_payload(edited)

    background.add_task(
        _record_when_finished,
        {"bundle": bundle},
        f"edit: {feature}.{request.parameter} = {request.value}",
        gate.user_id,
    )

    return {
        "success": bool(bundle.get("success")),
        "resolved": evidence,
        "plan": edit.as_dict(),
        "part_class": bundle.get("part_class", ""),
        "variables": bundle.get("variables", {}),
        "blueprint": bundle.get("blueprint"),
        "feature_tree": _feature_tree_for(bundle),
        "files": bundle.get("files", {}),
        "topology": bundle.get("topology") or {},
        "stats": bundle.get("stats"),
        "verification": bundle.get("verification") or {},
        # Always False here, and asserted rather than assumed: a retune cannot
        # reach the template, so the verdict above grades *this* geometry
        # against the contract it was designed to. If this ever reports True,
        # something has routed a structural edit through the parametric door.
        "contract_broken": blueprint_edit.template_changed(request.blueprint, edited),
        "generation_time_ms": bundle.get("generation_time_ms", 0),
        "request_id": bundle.get("request_id", ""),
        "error": bundle.get("error"),
    }
