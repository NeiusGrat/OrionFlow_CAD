"""Export the hand-modelled parametric hardware and check it against the mesh."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from build123d import export_brep, export_step

import json

from measure import load
from parts_lib import BEARINGS

ROOT = Path(__file__).resolve().parent.parent
BREP = ROOT / "work" / "modelled"
STEPS = ROOT / "out" / "parts"


def main() -> None:
    BREP.mkdir(parents=True, exist_ok=True)
    STEPS.mkdir(parents=True, exist_ok=True)
    # The bearing meshes do not close, and trimesh's volume for an open mesh is
    # not a number to grade against - it drifted by 7 points between two runs
    # while the model itself never changed. Use the sewn B-rep volume, as the
    # slab reconstruction does.
    sewn = {}
    sr = ROOT / "work" / "solid_report.json"
    if sr.exists():
        sewn = json.loads(sr.read_text())

    report = {}
    for name, spec in BEARINGS.items():
        solid = spec.build()
        mesh = load(name)
        bb = solid.bounding_box()
        ext = np.array([bb.size.X, bb.size.Y, bb.size.Z])
        ref = abs(mesh.volume)
        source = "mesh"
        if not mesh.is_watertight and sewn.get(name, {}).get("volume"):
            ref = sewn[name]["volume"]
            source = "sewn_brep"
        entry = {
            "faces": len(solid.faces()),
            "volume": round(float(solid.volume), 2),
            "reference_volume": round(float(ref), 2),
            "reference": source,
            "volume_error_pct": round(100 * (solid.volume - ref) / ref, 3),
            "extent_error_mm": round(float(np.max(np.abs(ext - mesh.extents))), 4),
            "balls": spec.balls,
            "od": spec.od, "bore": spec.bore, "width": spec.width,
        }
        export_brep(solid, str(BREP / f"{name}.brep"))
        export_step(solid, str(STEPS / f"{name}.step"))
        report[name] = entry
        print(f"{name:40s} faces={entry['faces']:4d} dV={entry['volume_error_pct']:7.2f}% "
              f"dExt={entry['extent_error_mm']:.4f}")
    (ROOT / "work" / "hardware_report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
