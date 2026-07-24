"""Phase-0 acceptance gate: the verifier must independently catch the
wrong_sidetype fault on master 83ca2dab2e.

Reproduces the real 2026-07-22 compiler bug end to end: strip SideType/Length2
from the two-sided pad, rebuild the damaged graph with the REAL compiler
(freecad/reconstruct.py under FreeCAD's Python), measure the rebuilt tool
solid, and compare against the CLEAN graph's Tier-1 prediction. The gate
passes only if the faulted build is flagged AND the clean build is not.

Usage:  python -m orion.gate_sidetype
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile

from . import tier1
from .faults import inject_wrong_sidetype

REL_TOL = 1e-4
TARGET = "83ca2dab2e"


def _freecad_python() -> str:
    for cand in (r"C:/Program Files/FreeCAD 1.1/bin/python.exe",):
        if os.path.exists(cand):
            return cand
    env = os.environ.get("ORION_FREECAD_PYTHON")
    if env and os.path.exists(env):
        return env
    raise RuntimeError("no FreeCAD python found")


def _load_master() -> dict:
    for p in glob.glob("freecad/training/sample_*.json"):
        s = json.load(open(p, encoding="utf-8"))
        if s["id"] == TARGET:
            return s["feature_graph"]
    raise RuntimeError(f"master {TARGET} not found")


def _build_and_measure(graph: dict, workdir: str, tag: str) -> float:
    """Real compiler, real measurement — same binaries as production."""
    gpath = os.path.join(workdir, f"{tag}.json")
    fpath = os.path.join(workdir, f"{tag}.FCStd")
    mpath = os.path.join(workdir, f"{tag}.measured.json")
    json.dump(graph, open(gpath, "w", encoding="utf-8"))
    py = _freecad_python()
    subprocess.run([py, "freecad/reconstruct.py", "--graph", gpath,
                    "--out", fpath], check=True, capture_output=True)
    subprocess.run([py, "orion/measure_fc.py", "--files", fpath,
                    "--out", mpath], check=True, capture_output=True)
    m = json.load(open(mpath, encoding="utf-8"))
    feats = m[tag]["features"]
    pads = [f for f in feats if f["type_id"] == "PartDesign::Pad"]
    return pads[0]["addsub_volume"]


def main() -> int:
    clean = _load_master()
    injected = inject_wrong_sidetype(clean)
    if injected is None:
        print("GATE ERROR: master has no two-sided extrusion to fault")
        return 2
    faulted, meta = injected

    pad = next(f for f in clean["features"]
               if f["type"] == "Pad" and
               (f["parameters"] or {}).get("SideType") == "Two sides")
    sk_id = next(d["source"] for d in clean["dependencies"]
                 if d["target"] == pad["id"] and d["kind"] == "profile")
    sk = next(s for s in clean["sketches"] if s["id"] == sk_id)
    area, _c, why = tier1.sketch_area(sk.get("geometry", []),
                                      sk.get("external_geometry", []))
    assert area is not None, why
    predicted, why = tier1.extrusion_volume(area, pad["parameters"])
    assert predicted is not None, why

    with tempfile.TemporaryDirectory() as wd:
        v_clean = _build_and_measure(clean, wd, "gate_clean")
        v_fault = _build_and_measure(faulted, wd, "gate_fault")

    err_clean = abs(v_clean - predicted) / predicted
    err_fault = abs(v_fault - predicted) / predicted
    flag_clean = err_clean > REL_TOL
    flag_fault = err_fault > REL_TOL

    print(f"fault injected      : {meta['fault']} on {meta['feature']}")
    print(f"predicted (frozen)  : {predicted:.4f} mm^3")
    print(f"clean build         : {v_clean:.4f} mm^3  err {err_clean:.2%}"
          f"  -> {'FLAGGED (BAD)' if flag_clean else 'pass'}")
    print(f"faulted build       : {v_fault:.4f} mm^3  err {err_fault:.2%}"
          f"  -> {'FLAGGED' if flag_fault else 'MISSED (BAD)'}")

    ok = flag_fault and not flag_clean
    print(f"\nGATE {'PASSED' if ok else 'FAILED'}: verifier "
          f"{'independently caught' if flag_fault else 'MISSED'} the "
          f"wrong_sidetype fault"
          + ("" if not flag_clean else " but also flagged the clean build"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
