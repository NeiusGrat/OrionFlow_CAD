"""Turn verified gear records into training rows.

``gear_family`` emits verified records — blueprint, verdict, measurements — but
not ``messages``. They were sitting outside the training corpus for that reason
alone. The target is the same Blueprint contract every other part uses, so a
gear is learned on exactly the same terms; only the derivation differs, because
an involute has no closed form in the expression language and its volume comes
from the profile builder's own polygon area.

    python -m orion.pack_gears --out data/forge/gears
"""

from __future__ import annotations

import argparse
import json
import os
import random

from .pack_sft import SYSTEM_PROMPT
from .prompt_styles import build_prompt


def think_block(rec: dict) -> str:
    v = rec["blueprint"]["variables"]
    m, z, alpha = v["module"], int(v["teeth"]), v["alpha"]
    rp = m * z / 2.0
    lines = [
        f"pitch radius rp = module*teeth/2 = {rp:g} mm",
        f"ISO 53 rack: addendum 1*m so tip r = {rp + m:g}, dedendum 1.25*m so "
        f"root r = {rp - 1.25 * m:g}",
        f"base radius rb = rp*cos({alpha:g} deg) — the flank is the involute "
        "of this circle, which is what makes the mesh conjugate",
        f"teeth = {z} is at or above the 17-tooth undercut limit at "
        f"{alpha:g} degrees",
        "the involute outline has no closed form in the expression language, "
        "so the body volume is asserted against the profile builder's own "
        "polygon area — prediction and geometry are the same polygon",
    ]
    for a in rec.get("verdict", {}).get("assertions", []):
        if a.get("kind") == "body_volume_profile" and a.get("measured"):
            lines.append(f"Predicted volume (from the profile area): "
                         f"{a['measured']:.4f} mm^3")
            break
    return "\n".join(lines)


def target_json(rec: dict) -> dict:
    bp = rec["blueprint"]
    return {k: bp[k] for k in ("part_class", "variables", "datums",
                               "design_plan", "assertions", "template")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default="data/forge/gears/gears.jsonl")
    ap.add_argument("--out", default="data/forge/gears")
    ap.add_argument("--seed", type=int, default=1602)
    args = ap.parse_args()

    recs = [json.loads(ln) for ln in open(args.src, encoding="utf-8")]
    rows = []
    for i, rec in enumerate(recs):
        if not rec.get("verified"):
            continue
        v = rec["blueprint"]["variables"]
        dims = [("module", v["module"], "module"),
                ("teeth", int(v["teeth"]), "tooth count"),
                ("bore_r", v["bore_r"], "bore radius"),
                ("t", v["t"], "face width")]
        prompt = build_prompt("spur gear", [], dims,
                              random.Random(args.seed * 1000 + i))
        rows.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content":
                    f"<think>\n{think_block(rec)}\n</think>\n\n"
                    + json.dumps(target_json(rec))},
            ],
            "meta": {"part_class": "spur_gear", "base_family": "spur_gear",
                     "teeth": int(v["teeth"]), "module": v["module"],
                     "segments": rec.get("segments")},
        })

    path = os.path.join(args.out, "gear_rows.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ln = sorted(sum(len(m["content"]) for m in r["messages"]) for r in rows)
    print(f"packed {len(rows)} gear rows from {len(recs)} records")
    if ln:
        print(f"  chars: median {ln[len(ln)//2]}  max {ln[-1]}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
