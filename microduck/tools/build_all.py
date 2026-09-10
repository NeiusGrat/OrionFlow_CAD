"""Run the whole reverse-engineering pipeline, source meshes to assembly.

    python tools/build_all.py            # everything
    python tools/build_all.py recon      # one stage, by name

Stages that need the OCC kernel are dispatched to FreeCAD's interpreter; the
rest run here. Each stage is idempotent, so a stage can be re-run on its own
after a change without redoing the ones before it.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))


def freecad_python() -> str:
    """Reuse the repo's resolver so this pipeline pins the same kernel as Orion."""
    sys.path.insert(0, str(ROOT.parent))
    from orion.freecad_python import freecad_python as resolve
    return resolve()


def _run(argv: list[str], label: str) -> None:
    t0 = time.time()
    proc = subprocess.run(argv, cwd=str(TOOLS), capture_output=True, text=True)
    tail = (proc.stdout or "").strip().splitlines()
    for line in tail[-6:]:
        print("   " + line)
    if proc.returncode != 0:
        print("   " + (proc.stderr or "").strip()[-600:])
        raise SystemExit(f"{label} failed with code {proc.returncode}")
    print(f"   -- {label} in {time.time() - t0:.1f}s")


STAGES = {
    "stage":    ("repair the source meshes",      lambda: _run([sys.executable, "stage_meshes.py"], "stage")),
    "solids":   ("mesh -> B-rep (FreeCAD)",       lambda: _run([freecad_python(), "fc_solids.py"], "solids")),
    "recon":    ("parametric slab rebuild",       lambda: _run([sys.executable, "recon_all.py"], "recon")),
    "hardware": ("parametric bearings",           lambda: _run([sys.executable, "build_hardware.py"], "hardware")),
    "place":    ("kinematic placements",          lambda: _run([sys.executable, "export_placements.py"], "place")),
    "assembly": ("assemble + STEP (FreeCAD)",     lambda: _run([freecad_python(), "fc_assembly.py"], "assembly")),
    "scene":    ("GLB + URDF",                    lambda: _run([sys.executable, "export_scene.py"], "scene")),
    "verify":   ("verification",                  lambda: _run([sys.executable, "verify.py"], "verify")),
}


def main() -> None:
    wanted = sys.argv[1:] or list(STAGES)
    unknown = [w for w in wanted if w not in STAGES]
    if unknown:
        raise SystemExit(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")
    for name in wanted:
        desc, fn = STAGES[name]
        print(f"\n[{name}] {desc}")
        fn()


if __name__ == "__main__":
    main()
