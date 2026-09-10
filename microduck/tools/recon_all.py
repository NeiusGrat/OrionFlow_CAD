"""Run the slab reconstruction over every part and keep what verifies.

A rebuild is only accepted when it lands within 2% of the mesh's volume and
0.05 mm of its bounding box on all three axes. Anything looser is not a
reconstruction, it is a different part, and it would be placed into the assembly
without anyone noticing.

Accepted parts are written to work/parametric as BREP; the FreeCAD assembler
prefers those over the faceted conversion.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from build123d import export_brep, export_step

from measure import load
from parts_lib import BEARINGS
from recon.rebuild import rebuild

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "work" / "slab"
STEPS = ROOT / "out" / "parts"


def main(names: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STEPS.mkdir(parents=True, exist_ok=True)
    report_path = ROOT / "work" / "recon_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}

    # A rebuild is keyed to the repaired mesh it was made from, so re-running
    # the sweep after a repair change redoes exactly the parts that moved.
    mesh_report = {}
    mr = ROOT / "work" / "mesh_report.json"
    if mr.exists():
        mesh_report = json.loads(mr.read_text())

    # the sewn B-rep volume is the yardstick for meshes that never closed
    solid_report = {}
    sr = ROOT / "work" / "solid_report.json"
    if sr.exists():
        solid_report = json.loads(sr.read_text())

    for name in names:
        prior = report.get(name)
        sha = mesh_report.get(name, {}).get("sha256")
        fresh = prior is not None and (sha is None or prior.get("mesh_sha256") == sha)
        if fresh and "--force" not in sys.argv:
            continue          # unchanged since its last rebuild
        if name in BEARINGS:
            # parts_lib models these by hand and does it far better - the slab
            # rebuild of the 22x16x4 bearing costs two minutes and lands at
            # 4 970 faces against 19. Spending the time to lose is pointless.
            report[name] = {"skipped": "hand-modelled in parts_lib",
                            "mesh_sha256": mesh_report.get(name, {}).get("sha256")}
            report_path.write_text(json.dumps(report, indent=2))
            print(f"{name:40s} skip (hand-modelled)", flush=True)
            continue
        t0 = time.time()
        try:
            mesh = load(name)
            ref = None
            if not mesh.is_watertight:
                ref = solid_report.get(name, {}).get("volume")
            r = rebuild(mesh, name, reference_volume=ref)
        except Exception as exc:
            report[name] = {"error": str(exc)[:160]}
            print(f"{name:40s} ERROR {exc}", flush=True)
            report_path.write_text(json.dumps(report, indent=2))
            continue

        entry = {
            "axis": {0: "X", 1: "Y", 2: "Z", -2: "XnYnZ"}.get(r.axis, "-"), "slabs": r.slabs, "faces": r.faces,
            "circles": r.circles, "volume": round(r.volume, 2),
            "reference_volume": round(r.mesh_volume, 2),
            "reference": "sewn_brep" if (not mesh.is_watertight
                                         and solid_report.get(name, {}).get("volume"))
                         else "mesh",
            "volume_error_pct": round(r.volume_error * 100, 3),
            "extent_error_mm": round(r.extent_error, 4),
            "extent_tol_mm": round(r.extent_tol, 4),
            "accepted": bool(r.ok), "seconds": round(time.time() - t0, 1),
            "mesh_sha256": mesh_report.get(name, {}).get("sha256"),
        }
        if r.ok and r.solid is not None:
            try:
                export_brep(r.solid, str(OUT / f"{name}.brep"))
                export_step(r.solid, str(STEPS / f"{name}.step"))
                entry["brep_kb"] = round((OUT / f"{name}.brep").stat().st_size / 1024, 1)
            except Exception as exc:
                entry["accepted"] = False
                entry["export_error"] = str(exc)[:120]
        report[name] = entry
        report_path.write_text(json.dumps(report, indent=2))
        print(f"{name:40s} axis={entry['axis']} slabs={entry['slabs']:2d} "
              f"faces={entry['faces']:5d} circ={entry['circles']:2d} "
              f"dV={entry['volume_error_pct']:7.3f}% dExt={entry['extent_error_mm']:7.4f} "
              f"{'KEEP' if entry['accepted'] else 'reject'} {entry['seconds']:5.1f}s",
              flush=True)

    n = sum(1 for v in report.values() if v.get("accepted"))
    print(f"\naccepted {n}/{len(report)} parametric rebuilds", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        args = sorted(p.stem for p in (ROOT / "work" / "repaired").glob("*.stl"))
    main(args)
