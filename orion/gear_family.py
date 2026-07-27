"""Generate and verify a family of involute spur gears.

The first capability tier beyond prismatic/revolved parts. Every gear is built
in FreeCAD and checked against its own assertions, exactly like the rest of the
corpus — the only new machinery is the ``body_volume_profile`` assertion kind,
which takes the predicted volume from the profile builder's own polygon area
because an involute flank has no closed form in the expression language.

Build cost is the binding constraint: FreeCAD's sketch solver scales badly with
segment count, and a gear is ``teeth * (2*flank_pts + 5)`` line segments. 301
segments builds in ~14 s; 505 exceeded the 90 s kernel budget entirely. The
sampler therefore caps total segments rather than sampling teeth freely.

    python -m orion.gear_family --n 40 --out data/forge/gears --workers 4
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor

from .blueprint import Blueprint, BlueprintError
from . import forge

MAX_SEGMENTS = 360          # ~15 s in FreeCAD; 500+ blows the build budget

# --------------------------------------------------------------------------- #
# The gear rules, in ONE place
# --------------------------------------------------------------------------- #
# Three constraints govern every involute gear this project builds. Each was
# discovered the hard way, and each was then re-derived (and once forgotten) by
# a second sampler:
#
#   1. teeth >= 17   — below that the flank undercuts at a 20 degree pressure
#                      angle. The gear's own precondition refuses to build,
#                      which is how a 16-tooth planet in the assembly sampler
#                      was caught.
#   2. teeth EVEN    — tip_diameter is a bounding box, and equals 2*ra only if
#                      a tooth centreline lands at both 0 and 180 degrees. Odd
#                      counts failed 16/16 against a *correct* gear.
#   3. segments      — teeth * (2*flank_pts + 5) must stay inside the kernel's
#                      build budget; 505 segments exceeded 90 s outright and
#                      396 sat 1.2 s under it, passing alone and failing under
#                      load.
#
# Any composer that builds gears must call these rather than restate them.
MIN_TEETH = 18              # >= 17 for undercut, rounded up to the next even


def flank_points_for(teeth: int) -> int:
    """Largest flank sampling that keeps this gear inside the build budget."""
    return max(3, min(6, int((MAX_SEGMENTS / max(teeth, 1) - 5) / 2)))


def segments_for(teeth: int, flank_pts: int | None = None) -> int:
    fp = flank_points_for(teeth) if flank_pts is None else flank_pts
    return int(teeth) * (2 * int(fp) + 5)


def teeth_problems(teeth: int, flank_pts: int | None = None) -> list[str]:
    """Every reason this tooth count is unusable. Empty list means usable."""
    out = []
    z = int(teeth)
    if z < MIN_TEETH:
        out.append(f"teeth {z} < {MIN_TEETH}: flank undercuts at 20 deg")
    if z % 2:
        out.append(f"teeth {z} is odd: tip_diameter bbox != 2*ra")
    segs = segments_for(z, flank_pts)
    if segs > 400:
        out.append(f"{segs} sketch segments exceeds the build budget")
    return out


def valid_teeth(teeth: int, flank_pts: int | None = None) -> bool:
    return not teeth_problems(teeth, flank_pts)


def even_teeth_choices(lo: int = MIN_TEETH, hi: int = 40) -> list[int]:
    """Every tooth count that satisfies all three rules."""
    return [z for z in range(max(lo, MIN_TEETH), hi + 1) if valid_teeth(z)]


DERIVATIONS = [
    ("rp = module*teeth/2 ; ra = rp + module ; rf = rp - 1.25*module",
     "ISO 53 / DIN 867 basic rack: addendum 1*m, dedendum 1.25*m"),
    ("rb = rp*cos(alpha) — the flank is the involute of this base circle",
     "conjugate action requires an involute of the base circle, so the "
     "pressure angle is constant through mesh"),
    ("V = A_involute(module, teeth, alpha)*t - pi*bore_r^2*t",
     "the gear outline has no closed form in the expression language; the "
     "area is taken exactly from the profile builder that emits the geometry, "
     "so prediction and geometry are the same polygon"),
]


def make_blueprint(module: float, teeth: int, bore_r: float, t: float,
                   alpha: float, fpts: int) -> Blueprint:
    return Blueprint(
        part_class="spur_gear",
        variables={"module": module, "teeth": float(teeth), "bore_r": bore_r,
                   "t": t, "alpha": alpha, "fpts": float(fpts)},
        datums={"A": "bottom face z=0 (primary)",
                "B": "bore axis (secondary)",
                "C": "first tooth flank (tertiary)"},
        design_plan={"derivation": [
            {"step": i + 1, "eq": eq, "why": why}
            for i, (eq, why) in enumerate(DERIVATIONS)]},
        assertions=[
            {"id": "bore_fits", "kind": "precondition", "tier": 1,
             "target": "module*teeth/2 - 1.25*module - bore_r - 2"},
            {"id": "no_undercut", "kind": "precondition", "tier": 1,
             "target": "teeth - 17"},
            {"id": "rim_guard", "kind": "precondition", "tier": 1,
             "target": "module*teeth/2 - 1.25*module - bore_r - 1.5*module"},
            {"id": "tip_diameter", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-06, "target": "module*teeth + 2*module"},
            {"id": "body", "kind": "body_volume_profile", "tier": 1,
             "tol_rel": 1e-06, "sketch": "s_gear", "length": "t"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
            {"id": "closed", "kind": "watertight", "tier": 1},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_gear", "type": "Sketch", "parameters": {}},
                {"id": "gear", "type": "Pad",
                 "rationale": "spur gear blank — involute flanks generated "
                              "from module, tooth count and pressure angle, "
                              "with a central bore for the shaft",
                 "parameters": {"Length": "t", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_gear", "plane": "XY", "profile": {
                    "builder": "involute_gear",
                    "args": {"module": "module", "teeth": "teeth",
                             "bore_r": "bore_r", "pressure_angle": "alpha",
                             "flank_pts": "fpts"}}},
            ],
            "dependencies": [
                {"source": "s_gear", "target": "gear", "kind": "profile"}],
        },
    ).freeze()


def sample(rng: random.Random) -> dict | None:
    """One gear whose segment count stays inside the build budget."""
    module = rng.choice([1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0])
    fpts = rng.choice([4, 5, 6])
    choices = [z for z in even_teeth_choices(hi=40) if valid_teeth(z, fpts)]
    if not choices:
        return None
    teeth = rng.choice(choices)
    alpha = rng.choice([14.5, 20.0, 20.0, 20.0, 25.0])
    rp = module * teeth / 2.0
    rf = rp - 1.25 * module
    # leave a real rim under the root, as a cut gear must have
    bore_max = rf - 1.5 * module
    if bore_max <= 2.5:
        return None
    bore_r = round(rng.uniform(2.5, bore_max) * 2) / 2.0
    t = round(rng.uniform(0.4, 1.6) * module * 6, 1)
    return {"module": module, "teeth": teeth, "bore_r": bore_r, "t": t,
            "alpha": alpha, "fpts": fpts}


def run_one(idx: int, params: dict, workdir: str) -> dict:
    row = {"idx": idx, **params, "verified": False, "error": None,
           "segments": None, "area": None, "volume": None, "elapsed": None}
    try:
        bp = make_blueprint(**params)
        graph = bp.resolve()
        segs = len(graph["sketches"][0]["geometry"])
        row["segments"] = segs
        row["area"] = graph["_analysis"]["s_gear"]["area"]
        t0 = time.time()
        v = forge.run_blueprint(bp, tag=f"gear_{idx:04d}", workdir=workdir)
        row["elapsed"] = round(time.time() - t0, 1)
        row["verified"] = bool(v.get("passed"))
        row["blueprint"] = bp.to_dict()
        row["verdict"] = v
        for a in v.get("assertions", []):
            if a.get("kind") == "body_volume_profile":
                row["volume"] = a.get("measured")
        if not row["verified"]:
            if v.get("failed_preconditions"):
                row["error"] = "precondition: " + ",".join(
                    str(p.get("id")) for p in v["failed_preconditions"])
            elif not v.get("build_ok"):
                log = (v.get("build_log", {}) or {})
                row["error"] = ("timeout" if log.get("timeout")
                                else "build: rc=%s" % log.get("returncode"))
            else:
                row["error"] = "assert: " + ",".join(
                    str(a.get("id")) for a in v.get("assertions", [])
                    if not a.get("passed"))
    except (BlueprintError, Exception) as e:      # noqa: BLE001
        row["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default="data/forge/gears")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1602)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    workdir = os.path.abspath(args.out)
    rng = random.Random(args.seed)

    todo, seen = [], set()
    while len(todo) < args.n:
        p = sample(rng)
        if not p:
            continue
        key = tuple(sorted(p.items()))
        if key in seen:
            continue
        seen.add(key)
        todo.append(p)

    print(f"generating {len(todo)} spur gears with {args.workers} workers")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda t: run_one(t[0], t[1], workdir),
                             enumerate(todo)))

    ok = [r for r in rows if r["verified"]]
    print(f"\nverified {len(ok)}/{len(rows)} ({100*len(ok)/max(len(rows),1):.0f}%)")
    if ok:
        segs = sorted(r["segments"] for r in ok)
        el = sorted(r["elapsed"] for r in ok if r["elapsed"])
        print(f"  segments: median {segs[len(segs)//2]}  max {segs[-1]}")
        print(f"  build time: median {el[len(el)//2]}s  max {el[-1]}s")
        tset = sorted({r["teeth"] for r in ok})
        mset = sorted({r["module"] for r in ok})
        print(f"  teeth: {tset}")
        print(f"  modules: {mset}")
    fails = {}
    for r in rows:
        if not r["verified"]:
            k = (r["error"] or "?").split(":")[0]
            fails[k] = fails.get(k, 0) + 1
    if fails:
        print("  failures:", fails)

    path = os.path.join(args.out, "gears.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            if r["verified"]:
                fh.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(ok)} verified gear records -> {path}")


if __name__ == "__main__":
    main()
