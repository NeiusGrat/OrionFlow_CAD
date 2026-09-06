"""Assemblies on the live path — many parts, placed, with their mates checked.

The single-part path proves a part matches the numbers it was built from. An
assembly has to prove something else, and ``orion.assembly`` already proves it
exactly: **non-interference by volume additivity**. If no two components share
space, the volume of their fusion equals the sum of their volumes, so

    |V_fused - sum(V_i)| / sum(V_i) <= tol

is a machine-precision proof that nothing interpenetrates — the one property an
assembly must have, and the one a shape-similarity score can never check.

Mates are not decoration here. A meshing centre distance, a planetary assembly
condition, a Grashof loop closure and a bolt's grip length are ordinary
preconditions: expressions over the assembly's variables, evaluated before any
geometry exists, so a mechanism that cannot close is refused rather than built
wrong.

None of that is new. ``orion/assembly.py`` and ``orion/assembly_spec.py`` have
carried eight verified assembly classes since the forge work, and the studio
could not reach any of them — the same way the spur gear was built, graded and
unreachable until it was put in a registry. This module is that registry plus
the translation from a verdict into the bundle the studio renders.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from typing import Any, Callable, Optional

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class AssemblySpec:
    """One assembly class: how to build it, and what it needs to be told."""

    def __init__(self, name: str, label: str, fn: Callable[..., dict],
                 params: dict[str, str], ints: tuple[str, ...] = (),
                 texts: tuple[str, ...] = ()):
        self.name = name
        self.label = label
        self.fn = fn
        #: slot name -> the question, kept in step with
        #: ``part_families.yaml``, which is what the interview
        #: actually asks from. Only the keys are load-bearing:
        #: they are the parameters the spec function is called
        #: with, and a name that does not match is a slot the
        #: user answers and the builder silently drops.
        self.params = params
        #: parameters the spec function requires as ``int``
        self.ints = ints
        #: parameters that stay strings (a strength class, a fit code)
        self.texts = texts

    def make(self, slots: dict) -> dict:
        kwargs: dict[str, Any] = {}
        for key in self.params:
            if key not in slots or slots[key] is None:
                continue
            value = slots[key]
            if key in self.texts:
                kwargs[key] = str(value)
            elif key in self.ints:
                kwargs[key] = int(round(float(value)))
            else:
                kwargs[key] = float(value)
        return self.fn(**kwargs)


def _catalogue() -> dict[str, AssemblySpec]:
    from orion import assembly_spec as S

    return {
        "bolted_joint": AssemblySpec(
            "bolted_joint", "bolted joint", S.bolted_joint,
            {"d": "What bolt diameter?",
             "plate_t": "How thick is each plate?",
             "n_bolts": "How many bolts?",
             "cls": "Bolt strength class?"},
            ints=("n_bolts",), texts=("cls",)),
        "bearing_stack": AssemblySpec(
            "bearing_stack", "bearing stack", S.bearing_stack,
            {"bore": "What is the bearing bore?",
             "ring_t": "How thick are the rings?",
             "ball_gap": "What is the ball gap?",
             "width": "How wide is the bearing?",
             "shaft_len": "How long is the shaft?"}),
        "planetary_stage": AssemblySpec(
            "planetary_stage", "planetary gear stage", S.planetary_stage_spec,
            {"module": "What module are the gears?",
             "z_sun": "How many teeth on the sun?",
             "z_planet": "How many teeth on each planet?",
             "n_planets": "How many planets?",
             "face_width": "How wide is each gear in the stage?",
             "sun_bore": "What is the sun bore?",
             "planet_bore": "What is each planet bore?"},
            ints=("z_sun", "z_planet", "n_planets")),
        "belt_drive": AssemblySpec(
            "belt_drive", "belt drive", S.belt_drive,
            {"d1": "What is the driving pulley diameter?",
             "d2": "What is the driven pulley diameter?",
             "centres": "What is the centre distance?",
             "width": "How wide are the pulleys?",
             "bore1": "What is the driving pulley bore?",
             "bore2": "What is the driven pulley bore?"}),
        "lead_screw_drive": AssemblySpec(
            "lead_screw_drive", "lead screw drive", S.lead_screw_drive,
            {"d": "What is the screw diameter?",
             "length": "How long is the screw?",
             "starts": "How many thread starts?",
             "nut_od": "What is the nut outside diameter?",
             "nut_len": "How long is the nut?",
             "travel": "How much travel is needed?"},
            ints=("starts",)),
        "spring_plunger": AssemblySpec(
            "spring_plunger", "spring plunger", S.spring_plunger,
            {"wire_d": "What is the spring wire diameter?",
             "coil_d": "What is the coil mean diameter?",
             "n_active": "How many active coils?",
             "free_len": "What is the free length?",
             "plunger_d": "What is the plunger diameter?",
             "bore_d": "What is the housing bore?",
             "preload_mm": "How much preload?",
             "stroke": "What stroke is needed?"}),
        "keyed_coupling": AssemblySpec(
            "keyed_coupling", "keyed coupling", S.keyed_coupling,
            {"shaft_d": "What is the shaft diameter?",
             "hub_od": "What is the hub outside diameter?",
             "hub_len": "How long is the hub?",
             "shaft_len": "How long is the shaft?",
             "torque_nm": "What torque must it carry, in Nm?"}),
        "four_bar": AssemblySpec(
            "four_bar", "four-bar linkage", S.four_bar,
            {"ground": "How long is the ground link?",
             "crank": "How long is the crank?",
             "coupler": "How long is the coupler?",
             "rocker": "How long is the rocker?",
             "theta_deg": "At what crank angle?",
             "link_w": "How wide is each link?",
             "link_t": "How thick is each link?",
             "hole_r": "What is the pin hole radius?"}),
    }


_CATALOGUE: Optional[dict[str, AssemblySpec]] = None


def catalogue() -> dict[str, AssemblySpec]:
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = _catalogue()
    return _CATALOGUE


def is_assembly(family: str) -> bool:
    return family in catalogue()


#: How an assembly assertion reads to an engineer. The ids come from
#: ``orion.assembly_spec``; anything not named here falls back to its id, which
#: is worse prose but never a wrong claim about what was checked.
_PROSE = {
    "no_interference": "No two parts occupy the same space",
    "part_count": "Every component is present",
    "fused_solids": "The components join as the mechanism expects",
    "assembly_condition": "The planets can all engage",
    "planet_clearance": "Adjacent planets clear each other",
    "sun_rim": "The sun keeps a rim under its tooth root",
    "grip": "The bolt grips the full stack",
    "thread_engagement": "Enough thread is engaged",
    "grashof": "The linkage closes and rotates",
    "loop_closure": "The linkage loop closes",
    "centre_distance": "The gears mesh at their true centre distance",
    "belt_wrap": "Enough belt wraps the small pulley",
    "key_shear": "The key carries the torque in shear",
    "spring_solid": "The spring does not go solid over its stroke",
}


def _checks(result: dict) -> list[dict]:
    """Assembly assertions as the verification rows the studio renders."""
    rows = []
    for a in result.get("assertions") or []:
        aid = str(a.get("id", ""))
        ok = bool(a.get("passed"))
        detail = ""
        if a.get("kind") == "no_interference":
            detail = (f"fused {a.get('measured'):.4f} against a component sum "
                      f"of {a.get('target'):.4f} mm³ "
                      f"(rel err {a.get('rel_err', 0):.2e})")
        elif a.get("measured") is not None:
            detail = f"measured {a.get('measured')}, expected {a.get('target')}"
        elif a.get("target") is not None:
            detail = f"holds at {a.get('target'):.4g}"
        rows.append({
            "id": f"{a.get('kind', 'assembly')}:{aid}",
            "label": _PROSE.get(aid, aid.replace("_", " ")),
            "status": "pass" if ok else "fail",
            "detail": detail,
            "evidence": {k: a[k] for k in ("target", "measured", "rel_err")
                         if k in a},
        })
    # Per-component verdicts are evidence too: an assembly of parts that each
    # failed their own assertions is not an assembly that works.
    for p in result.get("parts") or []:
        rows.append({
            "id": f"component:{p.get('id')}",
            "label": f"Component {p.get('id')} matches its own prediction",
            "status": "pass" if p.get("passed") else "fail",
            "detail": f"{len(p.get('assertions') or [])} assertion(s) checked",
            "evidence": {},
        })
    return rows


#: What each kernel failure means to the person who asked for a gearbox.
#:
#: The reasons are the engineering event; these are the sentences. Two of them
#: are about *us* rather than about the design, and they say so — a user whose
#: request was fine deserves to know the fault was ours. None of them names a
#: file, a container or an environment variable: the studio used to surface
#: "set ORION_FREECAD_PYTHON to one that can `import FreeCAD`" for this whole
#: class, which told the user nothing they could act on and told anyone else
#: how we are deployed.
#:
#: Keyed by the reason strings in ``orion.assembly``; a reason with no sentence
#: here falls back to the placement one rather than leaking a raw detail.
_KERNEL_MESSAGES = {
    "builder_unavailable": (
        "The CAD build service is not reachable right now, so this assembly "
        "could not be built. This is an outage on our side, not a limit of "
        "the design — the same request should work once it is back."
    ),
    "kernel_unavailable": (
        "No CAD kernel is available to build assemblies on this deployment. "
        "This is a configuration fault on our side, not a problem with what "
        "you asked for."
    ),
    "component_failed": (
        "One of the components could not be built as dimensioned, so the "
        "assembly was not completed."
    ),
    "placement_failed": (
        "The components were built but could not be placed and joined into a "
        "single assembly."
    ),
    "export_failed": (
        "The assembly was built and measured, but its CAD files could not be "
        "written, so there is nothing to download."
    ),
}

#: Reasons whose detail is about the *geometry*, so it helps the user to see
#: it. The availability reasons carry stack traces and hostnames instead, and
#: are logged rather than shown.
_DETAIL_IS_SAFE = ("component_failed", "placement_failed")

#: Marks of our own plumbing. A detail containing any of these is not the
#: geometry explanation ``_DETAIL_IS_SAFE`` assumes it is, whatever the reason
#: on it says.
#:
#: The reason-based rule alone was not enough, and its own test proved it: a
#: component build that fails *because* the kernel went missing is classified
#: ``component_failed`` and carries the interpreter error as its detail, so the
#: exact string this whole change exists to suppress came straight back out
#: under a different reason. Whether a detail is safe is a property of the
#: detail, not of the label attached to it.
_INTERNAL_MARKS = (
    "ORION_",
    "import FreeCAD",
    "FreeCAD interpreter",
    "/root/",
    "Traceback",
    ":\\",       # a Windows absolute path
)


def _detail_is_showable(detail: str) -> bool:
    return bool(detail) and not any(m in detail for m in _INTERNAL_MARKS)


def _kernel_message(exc) -> str:
    """A sentence for the user, plus the detail only where it is safe.

    Two independent conditions, and both must hold: the reason has to be one
    whose detail is about the design, *and* the detail must not name any of our
    own plumbing. Failing either, the user gets the sentence alone — which is
    still true, still actionable, and never a deployment detail.
    """
    base = _KERNEL_MESSAGES.get(exc.reason) or _KERNEL_MESSAGES["placement_failed"]
    if exc.reason in _DETAIL_IS_SAFE and _detail_is_showable(exc.detail):
        return f"{base} {exc.detail.strip()[:300]}"
    return base


def _refusal(rid: str, family: str, why: str, started: float,
             reason: str = "") -> dict:
    """A request that never reached the kernel. No geometry, and no pretence."""
    return {
        "success": False,
        "request_id": rid,
        "part_class": family,
        "assembly": True,
        "error": why,
        # Named so the studio, the tests and the logs all agree on which
        # failure this was without parsing the sentence.
        "failure_reason": reason,
        "verification": {"verdict": "refused", "checks": [], "failed": [],
                         "measured": {}},
        "files": {},
        "stats": {},
        "generation_time_ms": int((time.time() - started) * 1000),
    }


def build(family: str, slots: dict, request_id: Optional[str] = None) -> dict:
    """Build one assembly and return it in the studio's bundle shape.

    Component FCStd files stay in a scratch directory; the STEP and STL of the
    placed assembly are copied into ``settings.output_dir`` where the API
    already serves single parts from, so an assembly downloads exactly like a
    part does.
    """
    from orion import assembly as A
    from orion import assembly_spec as S

    spec_def = catalogue().get(family)
    if spec_def is None:
        raise KeyError(f"no assembly class {family!r}")

    rid = request_id or uuid.uuid4().hex[:12]
    started = time.time()
    workdir = tempfile.mkdtemp(prefix=f"asm_{rid}_")
    try:
        try:
            raw = spec_def.make(slots)
        except ValueError as exc:
            # The spec function itself refused — a count or a class it cannot
            # honour. That is a statement about the request, not a crash.
            return _refusal(rid, family, str(exc), started)
        if raw is None:
            # Some specs answer ``None`` for a mechanism that cannot exist at
            # all: a four-bar whose links cannot close has no crank angle to
            # draw, so there is no assembly to describe. Subscripting that
            # raised TypeError deep inside ``resolve_spec`` — a crash where a
            # refusal belongs, and the user got a stack trace instead of the
            # reason.
            return _refusal(
                rid, family,
                "these dimensions do not describe a mechanism that can be "
                "assembled — the links cannot reach each other in this "
                "configuration, so there is no geometry to build",
                started)
        spec = S.resolve_spec(raw)
        from app.services.blueprint_service import run_assembly_builder

        try:
            # The kernel is injected rather than imported by ``orion.assembly``:
            # in modal mode it dispatches to the FreeCAD container, and this
            # process never looks for a local interpreter at all.
            result = A.build_assembly(spec, workdir=workdir, tag=family,
                                      kernel=run_assembly_builder)
        except A.AssemblyKernelError as exc:
            logger.warning("assembly_kernel_failed", family=family,
                           reason=exc.reason, detail=exc.detail[:400])
            return _refusal(rid, family, _kernel_message(exc), started,
                            reason=exc.reason)

        checks = _checks(result)
        failed = [c for c in checks if c["status"] == "fail"]
        # An assembly whose preconditions refused it never reached the kernel,
        # so there is no geometry and no measurement — that is a refusal, not a
        # part that failed to verify.
        if result.get("refused"):
            names = ", ".join(str(p.get("id"))
                              for p in result.get("failed_preconditions") or [])
            return _refusal(
                rid, family,
                f"the mechanism does not close: {names}. These are mating "
                f"conditions checked before any geometry exists, so nothing "
                f"was built.", started)

        measured = result.get("measured") or {}
        bbox = measured.get("bbox") or []
        extent = ([round(bbox[i + 3] - bbox[i], 6) for i in range(3)]
                  if len(bbox) == 6 else None)

        files: dict[str, str] = {}
        outdir = str(settings.output_dir)
        os.makedirs(outdir, exist_ok=True)
        for kind in ("step", "stl"):
            src = result.get(kind)
            if src and os.path.exists(src):
                name = f"{rid}_{family}.{kind}"
                shutil.copy2(src, os.path.join(outdir, name))
                files[kind] = f"/outputs/{name}"

        verdict = "verified" if result.get("passed") else (
            "refused" if failed else "unproven")
        return {
            "success": bool(result.get("build_ok")),
            "request_id": rid,
            "part_class": family,
            "assembly": True,
            "error": result.get("error"),
            "verification": {
                "verdict": verdict,
                "checks": checks,
                "failed": failed,
                "measured": {
                    "volume_mm3": measured.get("fused_volume"),
                    "component_volume_sum_mm3": measured.get("sum_volume"),
                    "solids": measured.get("solids"),
                    "watertight": measured.get("watertight"),
                    "components": len(measured.get("parts") or []),
                },
            },
            "components": [
                {"id": p.get("id"), "volume_mm3": p.get("volume")}
                for p in measured.get("parts") or []
            ],
            "mates": spec.get("mates") or [],
            "variables": spec.get("variables") or {},
            "files": files,
            "stats": {"volume_mm3": measured.get("fused_volume"),
                      "bbox_mm": extent,
                      "components": len(measured.get("parts") or [])},
            "generation_time_ms": int((time.time() - started) * 1000),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
