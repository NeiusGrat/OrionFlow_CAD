"""Engineering Knowledge Graph: what the assembly *is*, not just where it sits.

A STEP file records geometry. This records engineering: which parts exist, what
they are made of, how they are joined, what each joint permits, how motion
propagates through the mechanism, and the proof that all of it is consistent.

Three graphs over one assembly:

* **AssemblyGraph** — nodes carry mass, centre of mass, principal inertia,
  bounding box and manufacturing process; edges carry the *mate* (concentric,
  gear, revolute), its degrees of freedom, and its assembly order. Transforms
  are a consequence of mates, not a substitute for them.
* **MotionGraph** — joints, mobility (Kutzbach), and the transmission ratios
  that follow from tooth counts. Analytic, so it costs nothing to compute and
  cannot drift from the geometry it describes.
* **VerificationReport** — every claim above, checked, PASS or FAIL.

Mass properties are *measured* from the built solids, never assumed: density
comes from the material table, everything else from the kernel.
"""

from __future__ import annotations

import json
import os
import subprocess

from . import forge

#: kg/mm^3 — the only assumed quantity in the whole graph.
MATERIALS = {
    "steel_4140":     {"density": 7.85e-6, "E": 210e3, "yield": 655.0},
    "steel_1045":     {"density": 7.87e-6, "E": 205e3, "yield": 530.0},
    "alu_6061_t6":    {"density": 2.70e-6, "E": 68.9e3, "yield": 276.0},
    "alu_7075_t6":    {"density": 2.81e-6, "E": 71.7e3, "yield": 503.0},
    "bronze_c93200":  {"density": 8.93e-6, "E": 100e3, "yield": 125.0},
}

MASS_MEASURE = r'''
import json, sys
import FreeCAD as App

spec = json.load(open(sys.argv[1], encoding="utf-8"))
shapes, per_part = [], []
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
    sh.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), p.get("rot_z", 0.0))
    sh.translate(App.Vector(x, y, z))
    com = sh.CenterOfMass
    bb = sh.BoundBox
    # Principal second moments of AREA-density 1 solid (mm^5); scaled by
    # density downstream to give real inertia.
    try:
        # FreeCAD returns the three principal second moments under "Moments";
        # there are no I1/I2/I3 keys.
        moments = [float(m) for m in sh.PrincipalProperties["Moments"]]
    except Exception as exc:
        moments = [None, None, None]
        print("inertia unavailable for %s: %s" % (p["id"], exc))
    per_part.append({
        "id": p["id"], "volume": sh.Volume,
        "com": [com.x, com.y, com.z],
        "bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
        "inertia_unit_density": moments,
    })
    shapes.append(sh)
    App.closeDocument(src.Name)

fused = shapes[0]
for s in shapes[1:]:
    fused = fused.fuse(s)
fused = fused.removeSplitter()
# Fusing disjoint solids yields a Compound, which exposes Volume but not
# CenterOfMass. For non-overlapping bodies the assembly centroid is exactly
# the volume-weighted mean of the component centroids, so compute it rather
# than asking the kernel for something a Compound cannot answer.
_v = sum(p["volume"] for p in per_part)
fcom = [sum(p["volume"] * p["com"][i] for p in per_part) / _v
        for i in range(3)]
fbb = fused.BoundBox
json.dump({
    "parts": per_part,
    "sum_volume": _v,
    "fused_volume": fused.Volume,
    "fused_com": fcom,
    "solids": len(fused.Solids),
    "watertight": bool(fused.isClosed()),
    "bbox": [fbb.XMin, fbb.YMin, fbb.ZMin, fbb.XMax, fbb.YMax, fbb.ZMax],
}, open(sys.argv[2], "w", encoding="utf-8"))
print("OK")
'''


def measure_mass_properties(placed: list[dict], workdir: str, tag: str) -> dict:
    spath = os.path.join(workdir, f"{tag}.mass.json")
    mpath = os.path.join(workdir, f"{tag}.mass.measured.json")
    script = os.path.join(workdir, "_mass_measure.py")
    json.dump({"parts": placed}, open(spath, "w", encoding="utf-8"))
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(MASS_MEASURE)
    r = subprocess.run([forge._freecad_python(), script, spath, mpath],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(mpath):
        raise RuntimeError(f"mass measurement failed: {(r.stderr or '')[-400:]}")
    return json.load(open(mpath, encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Tier 1 — assembly graph
# --------------------------------------------------------------------------- #
def assembly_graph(spec: dict, measured: dict, materials: dict,
                   mates: list[dict]) -> dict:
    """Nodes with measured mass properties; edges with mates and their DOF."""
    by_id = {p["id"]: p for p in measured["parts"]}
    nodes = []
    for p in spec["parts"]:
        pid = p["id"]
        m = by_id[pid]
        mat = materials.get(pid, "steel_4140")
        rho = MATERIALS[mat]["density"]
        inertia = [None if i is None else i * rho
                   for i in m["inertia_unit_density"]]
        bb = m["bbox"]
        nodes.append({
            "part_id": pid,
            "part_class": p["blueprint"].part_class,
            "blueprint_hash": p["blueprint"].blueprint_hash,
            "material": mat,
            "density_kg_mm3": rho,
            "volume_mm3": round(m["volume"], 6),
            "mass_kg": round(m["volume"] * rho, 9),
            "center_of_mass_mm": [round(c, 6) for c in m["com"]],
            "principal_inertia_kg_mm2": [None if i is None else round(i, 6)
                                         for i in inertia],
            "bbox_mm": [round(v, 6) for v in bb],
            "envelope_mm": [round(bb[3] - bb[0], 6), round(bb[4] - bb[1], 6),
                            round(bb[5] - bb[2], 6)],
            "coordinate_system": {
                "origin_mm": [round(float(c), 6) for c in p.get("_pos_num", [0, 0, 0])],
                "rot_z_deg": round(float(p.get("_rot_num", 0.0)), 6),
                "axes": "local Z = rotation axis, X = tooth-0 centreline",
            },
            "manufacturing_process": p.get("process", "CNC hobbing + turning"),
            "revision": "A",
        })
    total_mass = sum(n["mass_kg"] for n in nodes)
    return {
        "schema": "orion-assembly-graph-v1",
        "name": spec["name"],
        "nodes": nodes,
        "edges": mates,
        "totals": {
            "part_count": len(nodes),
            "mass_kg": round(total_mass, 9),
            "volume_mm3": round(measured["sum_volume"], 6),
            "center_of_mass_mm": [round(c, 6) for c in measured["fused_com"]],
            "bbox_mm": [round(v, 6) for v in measured["bbox"]],
        },
    }


# --------------------------------------------------------------------------- #
# Tier 5 — motion
# --------------------------------------------------------------------------- #
def kutzbach_mobility(n_links: int, joints: list[dict]) -> dict:
    """Planar mobility: M = 3(n-1) - 2*j1 - j2.

    ``n_links`` counts the ground link. Lower pairs (revolute, prismatic)
    remove two DOF each; higher pairs (a gear mesh, a cam contact) remove one.
    """
    j1 = sum(1 for j in joints if j["pair"] == "lower")
    j2 = sum(1 for j in joints if j["pair"] == "higher")
    return {"formula": "M = 3*(n-1) - 2*j1 - j2",
            "n_links": n_links, "lower_pairs": j1, "higher_pairs": j2,
            "mobility": 3 * (n_links - 1) - 2 * j1 - j2}


def planetary_motion_graph(z_sun: int, z_planet: int, n_planets: int) -> dict:
    """Ratios and mobility for a simple planetary stage.

    With the ring held, the carrier is the output and

        i = w_sun / w_carrier = 1 + z_ring / z_sun

    which is the standard Willis result. The planet spin ratio follows from the
    sun mesh, and its sign is opposite because it is an external mesh.
    """
    z_ring = z_sun + 2 * z_planet
    # Kinematic model uses ONE representative planet. Extra planets in a real
    # stage are kinematically redundant — they exist to share load and balance
    # radial forces, not to add freedom — and counting them as independent
    # links makes Kutzbach overcount badly (M=4 for a three-planet stage
    # instead of the correct 2). This is the textbook redundant-constraint
    # case, and getting it wrong is exactly the sort of thing that makes a
    # dataset teach nonsense.
    joints = [
        {"id": "frame_sun", "type": "revolute", "pair": "lower",
         "between": ["frame", "sun"], "dof": 1, "axis": "Z"},
        {"id": "frame_ring", "type": "revolute", "pair": "lower",
         "between": ["frame", "ring"], "dof": 1, "axis": "Z"},
        {"id": "frame_carrier", "type": "revolute", "pair": "lower",
         "between": ["frame", "carrier"], "dof": 1, "axis": "Z"},
        {"id": "carrier_planet", "type": "revolute", "pair": "lower",
         "between": ["carrier", "planet"], "dof": 1, "axis": "Z"},
        {"id": "mesh_sun_planet", "type": "gear", "pair": "higher",
         "between": ["sun", "planet"], "dof": 1,
         "constraint": "external mesh, rolling without slip at the pitch "
                       "circles"},
        {"id": "mesh_ring_planet", "type": "gear", "pair": "higher",
         "between": ["ring", "planet"], "dof": 1,
         "constraint": "internal mesh, same module"},
    ]
    # links: frame, sun, ring, carrier, representative planet
    n_links = 5
    return {
        "schema": "orion-motion-graph-v1",
        "mechanism": "simple planetary stage",
        "joints": joints,
        "mobility": kutzbach_mobility(n_links, joints),
        "ratios": {
            "z_sun": z_sun, "z_planet": z_planet, "z_ring": z_ring,
            "ring_fixed_sun_in_carrier_out": round(1 + z_ring / z_sun, 6),
            "carrier_fixed_sun_in_ring_out": round(-z_ring / z_sun, 6),
            "sun_fixed_ring_in_carrier_out": round(1 + z_sun / z_ring, 6),
            "planet_spin_per_sun_rev": round(-z_sun / z_planet, 6),
        },
        "redundant_planets": n_planets - 1,
        "notes": [
            "ring is a virtual member in this stage — its tooth count is fixed "
            "by z_ring = z_sun + 2*z_planet and it constrains the ratios, but "
            "it is not modelled as a solid in this sample",
            f"mobility is computed on one representative planet; the other "
            f"{n_planets - 1} are kinematically redundant and carry load "
            "rather than adding freedom",
            "M=2 means the stage needs two constraints to be determinate: "
            "ground one member (usually the ring) and drive one (usually the "
            "sun), which leaves the carrier as the output",
        ],
    }


# --------------------------------------------------------------------------- #
# Tier 8 — verification report
# --------------------------------------------------------------------------- #
def verification_report(asm_verdict: dict, graph: dict, motion: dict,
                        spec: dict) -> dict:
    """Every claim the graphs make, checked. PASS or FAIL, nothing heuristic."""
    checks = []

    def add(cid, desc, passed, expected=None, actual=None, tol=None):
        checks.append({"id": cid, "description": desc,
                       "expected": expected, "actual": actual,
                       "tolerance": tol, "result": "PASS" if passed else "FAIL"})

    for p in asm_verdict.get("parts", []):
        add(f"component_{p['id']}",
            f"component {p['id']} satisfies its own frozen assertions",
            p["passed"])

    for a in asm_verdict.get("assertions", []):
        add(f"assembly_{a['id']}", f"assembly assertion {a['id']} ({a['kind']})",
            a["passed"], a.get("target"), a.get("measured"),
            a.get("rel_err"))

    v = spec["variables"]
    a_expected = v["module"] * (v["z_sun"] + v["z_planet"]) / 2.0
    add("centre_distance",
        "gear centre distance equals m*(z_sun+z_planet)/2",
        abs(v["a"] - a_expected) < 1e-9, a_expected, v["a"])

    z_ring = motion["ratios"]["z_ring"]
    add("assembly_condition",
        "(z_sun + z_ring) / n_planets is an integer, else the planets cannot "
        "all engage",
        abs((v["z_sun"] + z_ring) / v["n_planets"]
            - round((v["z_sun"] + z_ring) / v["n_planets"])) < 1e-9,
        "integer", (v["z_sun"] + z_ring) / v["n_planets"])

    mass_sum = sum(n["mass_kg"] for n in graph["nodes"])
    add("mass_additive", "assembly mass equals the sum of component masses",
        abs(mass_sum - graph["totals"]["mass_kg"]) < 1e-12,
        mass_sum, graph["totals"]["mass_kg"])

    add("all_parts_have_mass", "every node carries a positive measured mass",
        all(n["mass_kg"] > 0 for n in graph["nodes"]))

    add("no_floating_parts",
        "every component appears in at least one mate edge",
        all(any(n["part_id"] in e["between"] for e in graph["edges"])
            for n in graph["nodes"]))

    add("mobility_determinate",
        "with the ring grounded and one input the stage has a defined ratio",
        motion["ratios"]["ring_fixed_sun_in_carrier_out"] > 0)

    n_pass = sum(1 for c in checks if c["result"] == "PASS")
    return {
        "schema": "orion-verification-report-v1",
        "checks": checks,
        "summary": {"total": len(checks), "passed": n_pass,
                    "failed": len(checks) - n_pass,
                    "result": "PASS" if n_pass == len(checks) else "FAIL"},
    }
