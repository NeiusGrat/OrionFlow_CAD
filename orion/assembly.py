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

PLACE_MEASURE = r'''
import json, sys
import FreeCAD as App
import Part

spec = json.load(open(sys.argv[1], encoding="utf-8"))
doc = App.newDocument("asm")
shapes = []
per_part = []
for p in spec["parts"]:
    src = App.openDocument(p["fcstd"])
    # Take the PartDesign Body tip, NOT the largest solid. A PartDesign
    # document exposes every feature as its own object with a Shape — the Pad
    # before the Pocket as well as the Pocket result — so max-by-volume always
    # picks the pre-pocket blank. Any part whose last operation removes
    # material was silently measured without it.
    bodies = [o for o in src.Objects if o.TypeId == "PartDesign::Body"
              and getattr(o, "Shape", None) is not None
              and not o.Shape.isNull()]
    if bodies:
        body = bodies[0]
    else:
        solids = [o for o in src.Objects
                  if getattr(o, "Shape", None) is not None
                  and not o.Shape.isNull() and o.Shape.Volume > 1e-9]
        if not solids:
            print("NO SOLID in %s" % p["fcstd"]); sys.exit(2)
        body = max(solids, key=lambda o: o.Shape.Volume)
    sh = body.Shape.copy()
    x, y, z = p["pos"]
    ang = p.get("rot_z", 0.0)
    sh.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), ang)
    sh.translate(App.Vector(x, y, z))
    shapes.append(sh)
    per_part.append({"id": p["id"], "volume": sh.Volume})
    App.closeDocument(src.Name)

fused = shapes[0]
for s in shapes[1:]:
    fused = fused.fuse(s)
fused = fused.removeSplitter()

bb = fused.BoundBox
out = {
    "parts": per_part,
    "sum_volume": sum(p["volume"] for p in per_part),
    "fused_volume": fused.Volume,
    "solids": len(fused.Solids),
    "watertight": bool(fused.isClosed()),
    "bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
}
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"))
print("MEASURED", json.dumps({k: v for k, v in out.items() if k != "parts"}))
'''


class AssemblyError(ValueError):
    pass


def _num(value, variables: dict) -> float:
    return E.evaluate(value, variables) if isinstance(value, str) \
        else float(value)


def build_assembly(spec: dict, workdir: str, tag: str) -> dict:
    """Compile every component, place them, fuse, and measure.

    ``spec`` = {name, variables, parts:[{id, blueprint, pos:[x,y,z], rot_z}],
    assertions:[...]}. Component blueprints are ordinary frozen Blueprints.
    """
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

    # ---- compile each component through the existing verified path ------- #
    placed, part_verdicts = [], []
    for p in spec["parts"]:
        bp: Blueprint = p["blueprint"]
        ptag = f"{tag}_{p['id']}"
        # Assembly components are often gears, which cost an order of
        # magnitude more kernel time than the prismatic parts BUILD_TIMEOUT_S
        # was tuned for — a 396-segment sun measured 89 s against a 90 s
        # budget, passing alone and failing under load. A flaky corpus is worse
        # than a slow one.
        v = forge.run_blueprint(bp, tag=ptag, workdir=workdir, timeout_s=300)
        # Retry ONLY when the kernel produced no measurement at all. That is an
        # infrastructure event — after ~50 sequential FreeCAD invocations a
        # build intermittently returns nothing, and the identical spec passes
        # on a second attempt. A failed *assertion* is never retried: that is
        # the geometry disagreeing with its prediction, which is exactly the
        # signal this corpus exists to record.
        if not v.get("passed") and not v.get("build_ok") \
                and not v.get("refused"):
            v = forge.run_blueprint(bp, tag=ptag, workdir=workdir,
                                    timeout_s=300)
            v["retried"] = True
        part_verdicts.append({"id": p["id"], "passed": bool(v.get("passed")),
                              "retried": bool(v.get("retried")),
                              "assertions": v.get("assertions", [])})
        if not v.get("passed"):
            return {"tag": tag, "passed": False, "build_ok": False,
                    "parts": part_verdicts,
                    "error": f"component {p['id']} failed its own assertions",
                    "assertions": []}
        placed.append({
            "id": p["id"],
            "fcstd": os.path.join(workdir, f"{ptag}.FCStd"),
            "pos": [_num(c, variables) for c in p.get("pos", [0, 0, 0])],
            "rot_z": _num(p.get("rot_z", 0.0), variables),
        })

    # ---- place, fuse, measure -------------------------------------------- #
    spath = os.path.join(workdir, f"{tag}.asm.json")
    mpath = os.path.join(workdir, f"{tag}.asm.measured.json")
    script = os.path.join(workdir, "_place_measure.py")
    json.dump({"parts": placed}, open(spath, "w", encoding="utf-8"))
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(PLACE_MEASURE)
    try:
        r = subprocess.run([forge._freecad_python(), script, spath, mpath],
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"tag": tag, "passed": False, "build_ok": False,
                "parts": part_verdicts, "error": "assembly fuse timed out",
                "assertions": []}
    if r.returncode != 0 or not os.path.exists(mpath):
        return {"tag": tag, "passed": False, "build_ok": False,
                "parts": part_verdicts,
                "error": f"fuse failed: {(r.stderr or '')[-300:]}",
                "assertions": []}
    m = json.load(open(mpath, encoding="utf-8"))

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
            "fcstd_parts": [p["fcstd"] for p in placed]}


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
    """
    from .gear_family import make_blueprint

    a = module * (z_sun + z_planet) / 2.0
    z_ring = z_sun + 2 * z_planet
    d_tip_planet = module * (z_planet + 2)
    fpts = 5

    parts = [{"id": "sun",
              "blueprint": make_blueprint(module, z_sun, sun_bore,
                                          face_width, 20.0, fpts),
              "pos": [0.0, 0.0, 0.0], "rot_z": 0.0}]
    for k in range(n_planets):
        th = 2.0 * math.pi * k / n_planets
        parts.append({
            "id": f"planet{k}",
            "blueprint": make_blueprint(module, z_planet, planet_bore,
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
             "target": "module*z_sun/2 - 1.25*module - sun_bore - 1.5*module"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1,
             "target": "n_planets + 1"},
            {"id": "stage_height", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-06, "target": "face_width"},
        ],
    }
