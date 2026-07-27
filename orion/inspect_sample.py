"""Open one packed training sample, build it for real, and leave the FCStd on
disk so a human can look at the part in FreeCAD.

The eval harness proves geometry *numerically* (predicted vs measured volume).
This proves it *visually* — pick a row, build it, and go open the file. Use it
before training to confirm the corpus is real, and during demo prep to choose
parts that look good on screen.

    python -m orion.inspect_sample --data data/forge/sft_v1/train.jsonl \
        --out builds/ --step

    python -m orion.inspect_sample --index 42 --out builds/    # exact row
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess

from .blueprint import Blueprint
from . import forge

EXPORT_SNIPPET = r"""
import sys, FreeCAD
doc = FreeCAD.openDocument(sys.argv[1])
doc.recompute()
shapes = [o for o in doc.Objects
          if getattr(o, "Shape", None) is not None and not o.Shape.isNull()]
if not shapes:
    print("no shape to export"); sys.exit(1)
# the Body (or the largest solid) is the part; sketches carry null volume
body = max(shapes, key=lambda o: getattr(o.Shape, "Volume", 0.0))
import Part
Part.export([body], sys.argv[2])
print("exported %s from %s" % (sys.argv[2], body.Name))
"""


def export_step(fcstd: str, step: str) -> bool:
    """Re-open the built document in FreeCAD and write a STEP next to it."""
    snippet = os.path.join(os.path.dirname(fcstd), "_export.py")
    with open(snippet, "w", encoding="utf-8") as fh:
        fh.write(EXPORT_SNIPPET)
    try:
        r = subprocess.run([forge._freecad_python(), snippet, fcstd, step],
                           capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, RuntimeError) as e:
        print(f"  STEP export failed: {e}")
        return False
    if r.returncode != 0:
        print(f"  STEP export failed: {(r.stderr or '')[-300:]}")
        return False
    return os.path.exists(step)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data/forge/sft_v1/train.jsonl")
    ap.add_argument("--out", default="builds")
    ap.add_argument("--index", type=int, default=None,
                    help="row number; omit for a random pick")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--step", action="store_true", help="also export STEP")
    ap.add_argument("--full-json", action="store_true")
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in open(args.data, encoding="utf-8")]
    idx = args.index if args.index is not None else \
        random.Random(args.seed).randrange(len(rows))
    row = rows[idx]
    os.makedirs(args.out, exist_ok=True)

    user = row["messages"][1]["content"]
    assistant = row["messages"][2]["content"]
    think, _, payload_text = assistant.partition("</think>")
    payload = json.loads(payload_text.strip())

    print("=" * 72)
    print(f"row {idx} of {len(rows)}   view={row['meta']['view']}   "
          f"family={row['meta']['base_family']}")
    print("=" * 72)
    print("\n--- PROMPT (what the model is given) ---")
    print(user)
    print("\n--- THINK (what the model must derive) ---")
    print(think.replace("<think>", "").strip())
    print("\n--- BLUEPRINT (what the model must emit) ---")
    t = payload["template"]
    print(f"part_class : {payload['part_class']}")
    print(f"variables  : {json.dumps(payload['variables'])}")
    print("features   : " + ", ".join(
        f"{f['id']}:{f['type']}" for f in t.get("features", [])))
    print("sketches   : " + ", ".join(
        f"{s['id']}[{s['profile']['builder']} on {s.get('plane','XY')}]"
        for s in t.get("sketches", [])))
    for f in t.get("features", []):
        if f.get("parameters"):
            print(f"  {f['id']}.parameters = {json.dumps(f['parameters'])}")
    print("assertions : " + ", ".join(
        f"{a['id']}({a['kind']})" for a in payload["assertions"]))
    if args.full_json:
        print(json.dumps(payload, indent=1))

    # ---- build it for real ------------------------------------------------ #
    print("\n--- BUILDING IN FREECAD ---")
    bp = Blueprint(**{k: v for k, v in payload.items()
                      if k != "blueprint_hash"}).freeze()
    print(f"hash {bp.blueprint_hash[:16]}  "
          f"(corpus {row['meta']['blueprint_hash'][:16]}) "
          f"{'MATCH' if bp.blueprint_hash == row['meta']['blueprint_hash'] else 'DIFFER'}")

    tag = f"inspect_{idx}"
    verdict = forge.run_blueprint(bp, tag=tag, workdir=os.path.abspath(args.out))
    fcstd = os.path.join(os.path.abspath(args.out), f"{tag}.FCStd")

    print(f"build_ok   : {verdict.get('build_ok')}")
    print(f"elapsed    : {verdict.get('elapsed_s')}s")
    print("\n  {:<18} {:<16} {:>16} {:>16} {:>10}".format(
        "assertion", "kind", "target", "measured", "rel_err"))
    for a in verdict.get("assertions", []):
        tgt = a.get("target")
        mea = a.get("measured")
        rel = a.get("rel_err")
        print("  {:<18} {:<16} {:>16} {:>16} {:>10}  {}".format(
            str(a.get("id"))[:18], str(a.get("kind"))[:16],
            f"{tgt:.4f}" if isinstance(tgt, float) else str(tgt),
            f"{mea:.4f}" if isinstance(mea, float) else "-",
            f"{rel:.2e}" if isinstance(rel, float) else "-",
            "PASS" if a.get("passed") else "FAIL"))
    print(f"\nVERDICT    : {'PASSED' if verdict.get('passed') else 'FAILED'}")

    if os.path.exists(fcstd):
        print(f"\nopen in FreeCAD:\n  {fcstd}")
        if args.step:
            step = os.path.join(os.path.abspath(args.out), f"{tag}.step")
            if export_step(fcstd, step):
                print(f"STEP:\n  {step}")
    else:
        print("\nno FCStd produced — see build log:")
        print((verdict.get("build_log", {}).get("stderr") or "")[-800:])


if __name__ == "__main__":
    main()
