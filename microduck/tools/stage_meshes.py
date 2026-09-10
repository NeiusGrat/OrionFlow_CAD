"""Stage every source mesh as a repaired, millimetre-scale STL.

The repair needs trimesh/pymeshfix and the B-rep conversion needs FreeCAD, and
those live in different interpreters. Rather than make either environment
import the other's dependencies, the repaired meshes are handed over on disk.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from meshrepair import load_mm, _shell_volume
import trimesh

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "meshes"
DST = ROOT / "work" / "repaired"


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    report = {}
    for f in sorted(SRC.glob("*.stl")):
        raw = trimesh.load(f, process=False)
        raw.apply_scale(1000.0)
        m = load_mm(f)
        m.export(DST / f.name)
        ref = _shell_volume(raw)
        report[f.stem] = {
            # Downstream stages key their caches on this: a part whose repaired
            # mesh did not change does not need reconstructing again.
            "sha256": hashlib.sha256((DST / f.name).read_bytes()).hexdigest(),
            "faces": int(len(m.faces)),
            "watertight": bool(m.is_watertight),
            "bodies": int(m.body_count),
            "volume_mm3": float(m.volume) if m.is_watertight else None,
            "extents_mm": [round(float(x), 4) for x in m.extents],
            "volume_drift_pct": round(100 * (abs(m.volume) - ref) / ref, 3) if ref else None,
        }
    (ROOT / "work" / "mesh_report.json").write_text(json.dumps(report, indent=2))
    tight = sum(v["watertight"] for v in report.values())
    print(f"staged {len(report)} meshes -> {DST}   watertight {tight}/{len(report)}")


if __name__ == "__main__":
    main()
