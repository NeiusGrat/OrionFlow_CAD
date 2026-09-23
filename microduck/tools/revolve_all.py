"""Rebuild the round parts as revolved solids and keep what verifies.

Only parts that are round are tried: the outer radius of every section along
the axis must agree to within ROUND_SPREAD across twelve sectors. A bracket
revolved about its bounding-box centre is not a reconstruction of anything,
and trying it only produces a solid for the gate to throw away.

Accepted rebuilds go to work/revolved/, which fc_assembly reads as its own
source so a slab or hand-modelled part is never overwritten by one.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
from build123d import export_brep

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recon.revolve import rebuild_revolved  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "work" / "revolved"

#: Median relative spread of the outer radius across sectors. The three round
#: parts measure 0.5-1.8%; the next-roundest, the M12 holder, is 21%.
ROUND_SPREAD = 0.05


def roundness(mesh) -> tuple[float, int]:
    """(median outer-radius spread, axis) for the roundest axis."""
    pts, _ = trimesh.sample.sample_surface(mesh, 20000, seed=0)
    best = (1.0, -1)
    for ax in range(3):
        o = [i for i in range(3) if i != ax]
        c = (mesh.bounds[0][o] + mesh.bounds[1][o]) / 2
        h = pts[:, ax]
        d = pts[:, o] - c
        r = np.hypot(d[:, 0], d[:, 1])
        th = np.arctan2(d[:, 1], d[:, 0])
        idx = np.digitize(h, np.linspace(h.min(), h.max(), 41))
        spread = []
        for b in range(1, 41):
            s = idx == b
            if s.sum() < 50:
                continue
            sec = np.digitize(th[s], np.linspace(-np.pi, np.pi, 13))
            rmax = [r[s][sec == k].max() for k in range(1, 13) if (sec == k).any()]
            spread.append(1.0 if len(rmax) < 10 else (max(rmax) - min(rmax)) / max(max(rmax), 1e-6))
        if spread and float(np.median(spread)) < best[0]:
            best = (float(np.median(spread)), ax)
    return best


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    solids = json.loads((ROOT / "work" / "solid_report.json").read_text())
    report = {}
    for path in sorted((ROOT / "work" / "repaired").glob("*.stl")):
        name = path.stem
        mesh = trimesh.load(path)
        spread, axis = roundness(mesh)
        if spread >= ROUND_SPREAD:
            continue
        t = time.time()
        r = rebuild_revolved(mesh, name, axis=axis, reference_volume=solids[name]["volume"])
        entry = {
            "axis": "XYZ"[r.axis] if r.axis >= 0 else "-",
            "roundness_spread": round(spread, 4),
            "faces": r.faces,
            "volume": round(r.volume, 2),
            "reference_volume": round(r.mesh_volume, 2),
            "volume_error_pct": round(r.volume_error * 100, 3),
            "extent_error_mm": round(r.extent_error, 4),
            "extent_tol_mm": round(r.extent_tol, 4),
            "accepted": bool(r.ok),
            "seconds": round(time.time() - t, 1),
        }
        report[name] = entry
        target = OUT / f"{name}.brep"
        if r.ok:
            export_brep(r.solid, str(target))
        elif target.exists():
            target.unlink()      # a stale accept must not outlive a failed rerun
        print(f"{name:20s} axis={entry['axis']} spread={spread*100:4.1f}% faces={r.faces:3d} "
              f"vol={entry['volume_error_pct']:6.2f}% ext={r.extent_error:.3f}/{r.extent_tol:.3f} "
              f"{'ACCEPT' if r.ok else 'reject'}")
    (ROOT / "work" / "revolve_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
