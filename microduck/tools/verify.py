"""Check the reconstruction against everything we can independently confirm.

Two kinds of check. The first compares the recovered model with what Pollen
Robotics published about the robot - 15 motors, under 800 g, 25 cm tall - which
is the only outside evidence available, since the source CAD is not public. The
second compares each rebuilt part with the mesh it came from.

Anything that fails prints as FAIL and the script exits non-zero.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from export_placements import POSES, world_transforms
from measure import load
from mjcf_model import Model
from recon.rebuild import VOLUME_TOL, extent_budget

ROOT = Path(__file__).resolve().parent.parent

#: Published by Pollen Robotics in the MicroDuck announcement.
CLAIMS = {"motors": 15, "max_mass_g": 800.0, "height_cm": 25.0}

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str) -> None:
    results.append((bool(ok), name, detail))


def main() -> int:
    model = Model()

    # --- against the published robot -------------------------------------
    counts = Counter(p[1] for p in model.placements())
    check(counts["xl330"] == CLAIMS["motors"], "motor count",
          f"{counts['xl330']} XL330 instances vs {CLAIMS['motors']} published")

    mass = model.total_mass() * 1000
    check(mass < CLAIMS["max_mass_g"], "mass",
          f"{mass:.1f} g from MJCF inertials vs published < {CLAIMS['max_mass_g']:.0f} g")

    W = world_transforms(model, POSES["zero"])
    pts = []
    for name in model.order:
        for inst in model.bodies[name].instances:
            m = load(inst.mesh)
            T = W[name] @ inst.T
            v = np.asarray(m.bounds)
            corners = np.array([[x, y, z] for x in v[:, 0] for y in v[:, 1] for z in v[:, 2]])
            pts.append((T[:3, :3] @ corners.T).T + T[:3, 3])
    pts = np.vstack(pts)
    height_cm = (pts[:, 2].max() - pts[:, 2].min()) / 10.0
    check(abs(height_cm - CLAIMS["height_cm"]) < 3.0, "height",
          f"{height_cm:.1f} cm at the zero pose vs published {CLAIMS['height_cm']:.0f} cm")

    check(len(model.joints) == 14, "joint count",
          f"{len(model.joints)} revolute joints recovered from the MJCF")

    # --- assembly completeness -------------------------------------------
    have = {p.stem for p in (ROOT / "work" / "brep").glob("*.brep")}
    for folder in ("slab", "modelled"):
        have |= {p.stem for p in (ROOT / "work" / folder).glob("*.brep")}
    need: set[str] = set()
    for f in sorted((ROOT / "work").glob("placements_*.json")):
        need |= {i["part"] for i in json.loads(f.read_text())["instances"]}
    check(not (need - have), "part coverage",
          f"{len(need)} distinct parts placed across all builds, "
          f"{len(need & have)} have solids"
          + (f", MISSING {sorted(need - have)}" if need - have else ""))

    source = {p.stem for p in (ROOT / "source" / "meshes").glob("*.stl")}
    check(not (source - need), "source coverage",
          f"{len(need & source)}/{len(source)} source meshes appear in a build"
          + (f", UNUSED {sorted(source - need)}" if source - need else ""))

    rollers = ROOT / "work" / "placements_rollers.json"
    if rollers.exists():
        rj = json.loads(rollers.read_text())
        wheels = [b for b in rj["bodies"]
                  if b["joint"] and b["joint"]["name"].startswith("passive_")]
        check(len(wheels) == 4, "roller variant",
              f"{len(rj['bodies'])} bodies, {len(wheels)} passive wheel joints, "
              f"{len(rj['instances'])} instances")

    # --- per-part fidelity -----------------------------------------------
    recon = {}
    rp = ROOT / "work" / "recon_report.json"
    if rp.exists():
        recon = json.loads(rp.read_text())
    # The budget is derived from the part here rather than read out of the
    # record: a report written before the field existed would otherwise fall
    # back to a default that never applied to it.
    bad = []
    for n, v in recon.items():
        if not v.get("accepted"):
            continue
        budget = v.get("extent_tol_mm") or extent_budget(load(n).extents)
        if (abs(v.get("volume_error_pct", 0)) > VOLUME_TOL * 100
                or v.get("extent_error_mm", 0) > budget):
            bad.append(n)
    kept = [n for n, v in recon.items() if v.get("accepted")]
    check(not bad, "parametric fidelity",
          f"{len(kept)} parametric rebuilds accepted, all within "
          f"{VOLUME_TOL * 100:g}% volume and their size-scaled extent budget"
          + (f"; OUT OF SPEC {bad}" if bad else ""))

    sr = ROOT / "work" / "solid_report.json"
    if sr.exists():
        solid = json.loads(sr.read_text())
        invalid = [n for n, v in solid.items() if not v.get("valid", False)]
        check(not invalid, "B-rep validity",
              f"{len(solid)} converted parts, {len(solid) - len(invalid)} valid"
              + (f"; INVALID {invalid}" if invalid else ""))

    width = max(len(n) for _, n, _ in results)
    print("\nMicroDuck reconstruction - verification\n" + "=" * 72)
    for ok, name, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:{width}s}  {detail}")
    failed = [n for ok, n, _ in results if not ok]
    print("=" * 72)
    print(f"  {len(results) - len(failed)}/{len(results)} checks passed"
          + (f"; failing: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
