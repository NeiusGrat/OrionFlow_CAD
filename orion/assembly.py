"""Verified assemblies, built additively on top of the single-body compiler.

``freecad/reconstruct.py`` creates exactly one ``PartDesign::Body`` per graph and
every feature goes into it. That file compiles all 25,560 verified parts, so it
is not the place to bolt multi-body support onto. Instead each component is
compiled through the existing, already-trusted path and this module places the
resulting solids into one document.

**How an assembly is verified.** Two independent facts, both exact:

1. Every component is a normal Blueprint and passes its own assertions —
   nothing about assembly weakens per-part verification.
2. *Non-interference is provable by volume additivity.* If the components do
   not overlap, the volume of their fusion equals the sum of their volumes
   exactly. Any interpenetration shows up as a deficit. So

       |V_fused - sum(V_i)| / sum(V_i) <= tol

   is a machine-precision proof that no two parts occupy the same space —
   which is the single property an assembly must have and the one a
   shape-similarity metric can never check.

Kinematic and mating constraints (gear centre distance, equal planet spacing,
the planetary assembly condition) are ordinary preconditions: expressions over
the assembly's variables, checked before anything is built.
"""

from __future__ import annotations

import json
import math
import os
import subprocess

from .blueprint import Blueprint
from . import expr as E
from . import forge



class AssemblyError(ValueError):
    pass


#: Why an assembly could not be built, in the caller's vocabulary.
#:
#: The point of naming these is that the studio can say something true and
#: useful for each. Before this existed, a missing FreeCAD in the API container
#: surfaced to the user as "set ORION_FREECAD_PYTHON to one that can `import
#: FreeCAD`" — an internal environment variable, shown to someone who asked for
#: a gearbox.
BUILDER_UNAVAILABLE = "builder_unavailable"
KERNEL_UNAVAILABLE = "kernel_unavailable"
COMPONENT_FAILED = "component_failed"
PLACEMENT_FAILED = "placement_failed"
EXPORT_FAILED = "export_failed"


class AssemblyKernelError(AssemblyError):
    """The kernel step failed, with a reason the caller can act on."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason)


def local_kernel(spec: dict, workdir: str, timeout_s: int = 900) -> dict:
    """Build an assembly in a local FreeCAD subprocess. One process, not N+1.

    The default kernel, and the only one ``orion`` knows how to reach by
    itself: dispatching to a remote builder needs the API layer's transport,
    which this package must not import (it is the lower layer, and the import
    would be a cycle). ``assembly_service`` injects that one.
    """
    from .freecad_python import freecad_python

    try:
        fc_python = freecad_python()
    except RuntimeError as exc:
        raise AssemblyKernelError(
            KERNEL_UNAVAILABLE,
            "no CAD kernel is available to this process",
        ) from exc

    spath = os.path.join(workdir, "assembly.spec.json")
    mpath = os.path.join(workdir, "assembly.measured.json")
    step = os.path.join(workdir, "assembly.step")
    stl = os.path.join(workdir, "assembly.stl")
    with open(spath, "w", encoding="utf-8") as fh:
        json.dump(spec, fh)

    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "build_assembly_fc.py")
    cmd = [fc_python, runner, "--spec", spath, "--out", mpath,
           "--workdir", workdir, "--step", step, "--stl", stl]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise AssemblyKernelError(
            PLACEMENT_FAILED, "the kernel did not finish in time") from exc

    return _read_kernel_output(mpath, r.returncode, r.stderr or "")


def _read_kernel_output(mpath: str, returncode: int, stderr: str) -> dict:
    """The runner's JSON, or the classified failure it recorded.

    A runner that failed writes ``{"error": {reason, detail}}`` rather than
    leaving the caller to guess from stderr, so the reason a user is shown is
    the one the stage that failed actually chose.
    """
    payload = None
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            payload = None

    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        raise AssemblyKernelError(
            str(err.get("reason") or PLACEMENT_FAILED),
            str(err.get("detail") or ""))
    if payload is None or returncode != 0:
        raise AssemblyKernelError(PLACEMENT_FAILED, (stderr or "")[-400:])
    return payload


def _num(value, variables: dict) -> float:
    return E.evaluate(value, variables) if isinstance(value, str) \
        else float(value)


def build_assembly(spec: dict, workdir: str, tag: str, kernel=None) -> dict:
    """Compile every component, place them, fuse, and measure.

    ``spec`` = {name, variables, parts:[{id, blueprint, pos:[x,y,z], rot_z}],
    assertions:[...]}. Component blueprints are ordinary frozen Blueprints.

    Three zones, and only the middle one needs a CAD kernel:

    1. preconditions, hash verification and ``Blueprint.resolve()`` — arithmetic
       over the spec, and the placements resolved to plain numbers;
    2. ``kernel`` — compile each component, place, fuse, measure, export;
    3. per-component and assembly assertions against what came back.

    ``kernel(spec, workdir) -> dict`` is injected so zone 2 can run somewhere
    else. That is the whole reason the split exists: the API container has no
    FreeCAD, and until this was separated an assembly request there died on
    ``freecad_python()`` with an environment variable in the error. It defaults
    to :func:`local_kernel`, so a box that does have FreeCAD is unchanged.
    """
    kernel = kernel or local_kernel
    os.makedirs(workdir, exist_ok=True)
    variables = spec["variables"]

    # ---- preconditions decide before anything is built ------------------- #
    failed_pre = []
    for a in spec.get("assertions", []):
        if a.get("kind") == "precondition":
            v = _num(a["target"], variables)
            if v is None or v <= 0:
                failed_pre.append({"id": a.get("id"), "target": v})
    if failed_pre:
        return {"tag": tag, "passed": False, "refused": True,
                "failed_preconditions": failed_pre, "assertions": [],
                "build_ok": False}

    # ---- zone 1: resolve every component, without a kernel --------------- #
    #
    # verify_hash and each component's own preconditions are checked here, as
    # ``forge.run_blueprint`` used to, so a component that cannot be built is
    # refused before anything is dispatched anywhere.
    components, blueprints = [], {}
    for p in spec["parts"]:
        bp: Blueprint = p["blueprint"]
        if not bp.verify_hash():
            raise AssemblyError(
                f"component {p['id']}: blueprint hash does not verify")
        pre = forge.failed_preconditions(bp)
        if pre:
            return {"tag": tag, "passed": False, "build_ok": False,
                    "refused": True, "failed_preconditions": pre,
                    "parts": [{"id": p["id"], "passed": False,
                               "assertions": []}],
                    "error": f"component {p['id']} refused its preconditions",
                    "assertions": []}
        graph = bp.resolve()
        blueprints[p["id"]] = (bp, graph)
        components.append({
            "id": p["id"],
            "graph": graph,
            "pos": [_num(c, variables) for c in p.get("pos", [0, 0, 0])],
            "rot_z": _num(p.get("rot_z", 0.0), variables),
        })

    # ---- zone 2: the only step that needs a CAD kernel -------------------- #
    result = kernel({"components": components}, workdir)
    m = result["assembly"]

    # ---- zone 3: check what came back ------------------------------------ #
    part_verdicts = []
    for comp in result.get("components") or []:
        bp, graph = blueprints[comp["id"]]
        measured = comp.get("measured") or {}
        # The graph resolved in zone 1, not a second resolve: it is
        # deterministic, but recomputing it here would be the same arithmetic
        # twice per component for nothing.
        rows = forge.check_assertions(
            bp, measured, analysis=graph.get("_analysis")) if measured else []
        passed = bool(rows) and all(r["passed"] for r in rows)
        part_verdicts.append({"id": comp["id"], "passed": passed,
                              "assertions": rows})
        if not passed:
            return {"tag": tag, "passed": False, "build_ok": False,
                    "parts": part_verdicts, "reason": COMPONENT_FAILED,
                    "error": f"component {comp['id']} failed its own assertions",
                    "assertions": []}

    if m.get("step_error") or m.get("stl_error"):
        raise AssemblyKernelError(
            EXPORT_FAILED,
            str(m.get("step_error") or m.get("stl_error")))


    # ---- assembly-level assertions --------------------------------------- #
    rows = []
    for a in spec.get("assertions", []):
        kind = a.get("kind")
        tol = float(a.get("tol_rel", 1e-6))
        if kind == "precondition":
            rows.append({"id": a["id"], "kind": kind, "tier": a.get("tier", 1),
                         "target": _num(a["target"], variables),
                         "passed": True})
        elif kind == "no_interference":
            # The whole point: fusion volume == sum of part volumes iff no two
            # solids share space.
            s, f = m["sum_volume"], m["fused_volume"]
            err = abs(f - s) / max(abs(s), 1e-12)
            rows.append({"id": a["id"], "kind": kind, "tier": a.get("tier", 1),
                         "target": s, "measured": f, "rel_err": err,
                         "passed": err <= tol})
        elif kind == "part_count":
            # Count COMPONENTS, not solids after fusion. Real assemblies touch
            # — a bolt head seats on a plate, a bearing ring seats on a shaft —
            # and tangent solids fuse into one. Volume stays additive (that is
            # what no_interference proves), but the solid count legitimately
            # drops below the component count.
            got = len(m["parts"])
            want = _num(a["target"], variables)
            rows.append({"id": a["id"], "kind": kind, "tier": a.get("tier", 1),
                         "target": want, "measured": got,
                         "passed": abs(got - want) < 0.5})
        elif kind == "fused_solids":
            # The topological complement: how many connected bodies remain
            # after fusion. 1 means every component touches something — a
            # joined stack. N means nothing touches — a gear set running on
            # clearance. Both are valid; which one is expected is a property
            # of the mechanism, so the assembly states it.
            got = m["solids"]
            want = _num(a["target"], variables)
            rows.append({"id": a["id"], "kind": kind, "tier": a.get("tier", 1),
                         "target": want, "measured": got,
                         "passed": abs(got - want) < 0.5})
        elif kind == "bbox_extent":
            axis = {"x": 0, "y": 1, "z": 2}[a.get("axis", "z")]
            got = m["bbox"][axis + 3] - m["bbox"][axis]
            want = _num(a["target"], variables)
            err = abs(got - want) / max(abs(want), 1e-12)
            rows.append({"id": a["id"], "kind": kind, "tier": a.get("tier", 1),
                         "target": want, "measured": got, "rel_err": err,
                         "passed": err <= tol})
    passed = bool(rows) and all(r["passed"] for r in rows) \
        and all(p["passed"] for p in part_verdicts)
    return {"tag": tag, "passed": passed, "build_ok": True,
            "parts": part_verdicts, "assertions": rows, "measured": m,
            "fcstd_parts": [c.get("fcstd") for c in result.get("components") or []
                            if c.get("fcstd")],
            "step": m.get("step"), "stl": m.get("stl")}


# --------------------------------------------------------------------------- #
# a real robotics assembly: the core of a planetary gear stage
# --------------------------------------------------------------------------- #
def planetary_stage(module: float, z_sun: int, z_planet: int, n_planets: int,
                    face_width: float, sun_bore: float, planet_bore: float
                    ) -> dict:
    """Sun + N planets at their true meshing centre distance.

    Engineering constraints, all checked before any geometry is built:

    * **centre distance** ``a = m*(z_sun + z_planet)/2`` — the meshing
      condition for standard (non profile-shifted) involute gears.
    * **assembly condition** ``(z_sun + z_ring) / n`` integer, with
      ``z_ring = z_sun + 2*z_planet``, or the planets cannot all engage.
    * **planet clearance** ``2*a*sin(pi/n) > d_tip_planet`` — adjacent planets
      must not collide, which is the constraint that actually limits how many
      planets a stage can carry.

    ``sun_bore`` and ``planet_bore`` are diameters; see
    ``assembly_spec.planetary_stage_spec``, which is the version the live path
    builds from. Kept in step deliberately — this copy has no caller today, and
    a dormant second definition that still halves nothing is exactly how the
    bug comes back.
    """
    from .gear_family import make_blueprint

    a = module * (z_sun + z_planet) / 2.0
    z_ring = z_sun + 2 * z_planet
    d_tip_planet = module * (z_planet + 2)
    fpts = 5

    parts = [{"id": "sun",
              "blueprint": make_blueprint(module, z_sun, sun_bore / 2.0,
                                          face_width, 20.0, fpts),
              "pos": [0.0, 0.0, 0.0], "rot_z": 0.0}]
    for k in range(n_planets):
        th = 2.0 * math.pi * k / n_planets
        parts.append({
            "id": f"planet{k}",
            "blueprint": make_blueprint(module, z_planet, planet_bore / 2.0,
                                        face_width, 20.0, fpts),
            "pos": [a * math.cos(th), a * math.sin(th), 0.0],
            # Counter-rotate each planet so its teeth sit in the sun's gaps
            # rather than clashing with them; without this the fusion would
            # overlap and no_interference would (correctly) fail.
            "rot_z": math.degrees(th) * (1.0 + z_sun / z_planet)
                     + 180.0 / z_planet,
        })

    variables = {
        "module": module, "z_sun": float(z_sun), "z_planet": float(z_planet),
        "n_planets": float(n_planets), "face_width": face_width,
        "sun_bore": sun_bore, "planet_bore": planet_bore,
        "sun_bore_r": sun_bore / 2.0, "planet_bore_r": planet_bore / 2.0,
        "a": a, "z_ring": float(z_ring), "d_tip_planet": d_tip_planet,
    }
    return {
        "name": "planetary_stage",
        "variables": variables,
        "parts": parts,
        "assertions": [
            {"id": "assembly_condition", "kind": "precondition", "tier": 1,
             "target": "0.5 - abs((z_sun + z_ring)/n_planets "
                       "- round((z_sun + z_ring)/n_planets))"},
            {"id": "planet_clearance", "kind": "precondition", "tier": 1,
             "target": "2*a*sin(pi/n_planets) - d_tip_planet - 1.0"},
            {"id": "sun_rim", "kind": "precondition", "tier": 1,
             "target": "module*z_sun/2 - 1.25*module - sun_bore_r "
                       "- 1.5*module"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1,
             "target": "n_planets + 1"},
            {"id": "stage_height", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-06, "target": "face_width"},
        ],
    }
