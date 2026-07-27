"""Sweep realistic prose prompts through the live model and verify every one.

Picking demo prompts by intuition is how a demo dies: the interesting-sounding
ask turns out to sit outside the trained distribution. This runs a candidate set
end to end — generate, build, verify — and reports which ones are safe to put in
front of an audience, with a STEP file for each that passes.

    python -m orion.demo_sweep --out builds/demo_sweep

Prompts are phrased the way an engineer speaks, not the way the training set
formats a spec, because that is what will happen live.
"""

from __future__ import annotations

import argparse
import json
import os
import time

from . import forge
from .demo_once import SYSTEM, ask, classify
from .eval_blueprint import extract_blueprint, to_blueprint
from .inspect_sample import export_step

PROMPTS: list[tuple[str, str]] = [
    ("l_bracket", "I need an L bracket to bolt a 40 mm rail to a wall. Roughly 90 long, 8 thick."),
    ("mount_plate", "Design a mounting plate 140 x 90 and 12 thick with a central bore for a 30 mm shaft."),
    ("flange", "I need a round mounting flange, 120 outside diameter, 14 thick, with a 40 mm bore and six bolt holes on a 95 bolt circle."),
    ("u_channel", "Give me a U channel 200 long, 60 wide, 45 tall, 6 mm walls."),
    ("tee_plate", "A T-shaped bracket plate, 160 across the bar and 80 down the stem, 10 thick, with a fixing bore at each of the three arm ends."),
    ("box_shell", "A cast box shell 150 x 100 x 60 with 6 mm walls and an 8 mm floor."),
    ("stepped_block", "A stepped block 120 long, 70 wide, 40 tall with a 25 x 20 rabbet along the top edge."),
    ("wheel_hub", "A wheel hub with a 100 mm flange, 26 mm centre bore, and five lug holes."),
    ("pillow_block", "A pillow block bearing housing for a 35 mm shaft, 90 wide at the base."),
    ("clevis", "A clevis mount with a 16 mm pin bore and 50 mm jaw opening."),
    ("gusset", "A triangular gusset plate 120 x 120, 10 thick, with a bolt hole in each corner."),
    ("cyl_shell", "A cylindrical shell 90 outside diameter, 140 tall, 5 mm wall, closed at the bottom."),
    ("bent_lever", "A bent lever with a 70 mm arm and a 90 mm arm, 22 wide, 12 thick, pivot bore at the elbow."),
    ("finned_rail", "A finned heat-sink rail 180 long with a 60 x 10 base and cooling fins along the top."),
    ("slotted_rail", "A slotted rail 220 long and 50 wide with a longitudinal slot for adjustment."),
    ("v_pulley", "A V-belt pulley, 120 outside diameter, 30 wide, 20 mm bore."),
    ("tapered_collar", "A tapered collar, 70 large diameter tapering to 50, 40 tall, 25 mm bore."),
    ("cross_rib", "A cross-ribbed plate 140 x 140 and 8 thick with stiffening ribs across the back."),
    ("bearing_carrier", "A bearing carrier plate 110 x 110, 16 thick, with a 52 mm bearing bore and four mounting holes."),
    ("hex_hub", "A hex hub, 60 across flats, 45 tall, with a 20 mm through bore."),
    ("drafted_pedestal", "A cast pedestal 90 x 70 at the base and 55 tall, drafted 3 degrees for moulding."),
    ("duct_reducer", "A duct reducer from 100 mm down to 60 mm over a 90 mm length, 3 mm wall."),
    ("valve_block", "A valve block 100 x 80 x 50 with a cross-drilled 12 mm bore."),
    ("planet_carrier", "A planet carrier plate, 130 diameter, 14 thick, with three planet pin bores on a 45 mm radius."),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="orionflow")
    ap.add_argument("--out", default="builds/demo_sweep")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--only", help="comma-separated names to run")
    ap.add_argument("--step", action="store_true", default=True)
    ap.add_argument("--repair", action="store_true",
                    help="retry each failure once with a diagnosis")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    workdir = os.path.abspath(args.out)
    wanted = set(args.only.split(",")) if args.only else None
    todo = [(n, p) for n, p in PROMPTS if not wanted or n in wanted]

    tail = ("  Choose sensible values for anything I have not given. Give the "
            "parametric feature tree with every dimension as an expression "
            "over named variables, and state the volume you expect and why.")
    results = []
    for i, (name, prompt) in enumerate(todo, 1):
        row = {"name": name, "prompt": prompt, "verified": False,
               "error": None, "gen_s": None, "volume": None, "features": 0}
        print(f"[{i}/{len(todo)}] {name:18s} ", end="", flush=True)
        try:
            t0 = time.time()
            completion = ask(args.endpoint, args.model,
                             [{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": prompt + tail}],
                             args.max_tokens, args.temperature)
            row["gen_s"] = round(time.time() - t0, 1)
            payload = extract_blueprint(completion)
            row["features"] = len(payload.get("template", {})
                                  .get("features", []))
            # to_blueprint and run_blueprint raise on exactly the mechanical
            # errors most worth retrying — a duplicate feature id, a builder
            # name one character off, a boolean where a number belongs. Catch
            # them into an error string so the repair path below sees them
            # instead of the outer handler swallowing them first.
            verdict: dict = {}
            try:
                bp = to_blueprint(payload)
                verdict = forge.run_blueprint(bp, tag=name, workdir=workdir)
                row["verified"] = bool(verdict.get("passed"))
                if not row["verified"]:
                    row["error"] = classify(verdict)
            except Exception as inner:               # noqa: BLE001
                kind = ("freeze" if "Blueprint" in type(inner).__name__
                        else "build")
                row["error"] = f"{kind}: {str(inner)[:150]}"
            for a in verdict.get("assertions", []):
                if a.get("kind") in ("body_volume", "body_mesh_converged"):
                    row["volume"] = a.get("measured")
            if row["verified"] and args.step:
                fc = os.path.join(workdir, f"{name}.FCStd")
                if os.path.exists(fc):
                    export_step(fc, os.path.join(workdir, f"{name}.step"))
            # Out-of-distribution prose produces recoverable errors far more
            # often than the in-distribution test split did — an invented
            # builder one character off the real name, a guard on the wrong
            # variable. Worth measuring whether one diagnosed retry rescues it.
            if not row["verified"] and args.repair:
                from .repair_loop import build_repair_messages, diagnose
                d = diagnose(payload, row["error"] or "", verdict)
                fixed = ask(args.endpoint, args.model,
                            build_repair_messages(
                                [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": prompt + tail}],
                                completion, d),
                            args.max_tokens, args.temperature)
                bp2 = to_blueprint(extract_blueprint(fixed))
                v2 = forge.run_blueprint(bp2, tag=name + "_fix",
                                         workdir=workdir)
                if v2.get("passed"):
                    row["verified"] = True
                    row["repaired"] = True
                    row["error"] = None
        except Exception as e:                       # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {str(e)[:90]}"
        print(("OK  " if row["verified"] else "FAIL") +
              f"  {row['gen_s']}s  feats={row['features']}"
              + (f"  {row['error'][:60]}" if row["error"] else ""))
        results.append(row)

    ok = [r for r in results if r["verified"]]
    print("\n" + "=" * 70)
    print(f"  {len(ok)}/{len(results)} verified "
          f"({100.0 * len(ok) / max(len(results), 1):.0f}%)")
    if ok:
        gens = sorted(r["gen_s"] for r in ok)
        print(f"  generation: median {gens[len(gens)//2]:.0f}s  "
              f"max {gens[-1]:.0f}s")
        print("\n  SAFE FOR DEMO (richest feature trees first):")
        for r in sorted(ok, key=lambda x: -x["features"])[:10]:
            print(f"    {r['name']:18s} {r['features']:2d} features  "
                  f"{r['gen_s']:5.0f}s   {r['prompt'][:52]}")
    bad = [r for r in results if not r["verified"]]
    if bad:
        print("\n  AVOID:")
        for r in bad:
            print(f"    {r['name']:18s} {str(r['error'])[:70]}")
    print("=" * 70)

    with open(os.path.join(workdir, "sweep.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
