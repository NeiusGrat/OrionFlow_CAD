"""Turn validated variants into aligned training pairs.

For every accepted variant (freecad/variants/accepted.jsonl) this emits:
  - 5 prompt levels (vague -> standard -> expert -> conversational -> spec),
    generated FROM the injected parameter values, so prompt<->geometry
    alignment is guaranteed by construction
  - OFL code derived deterministically FROM the graph geometry (dual-emit:
    the FeatureGraph stays the second representation), executed in-process
    and accepted only when its solid volume matches the variant's analytic
    volume within 1%

Outputs under freecad/variants/:
  training_pairs.jsonl   — one row per (variant x level) with prompt, ofl_code,
                           graph path, values, volumes
  ofl_chat.jsonl         — chat-format rows ready for fine-tuning on OFL

Usage:
    python -m freecad.training_pairs            # all accepted variants
    python -m freecad.training_pairs --limit 20
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from .config import PKG_DIR

VARIANTS_DIR = PKG_DIR / "variants"
ACCEPTED = VARIANTS_DIR / "accepted.jsonl"
PAIRS_OUT = VARIANTS_DIR / "training_pairs.jsonl"
CHAT_OUT = VARIANTS_DIR / "ofl_chat.jsonl"

SYSTEM_PROMPT = (
    "You are OrionFlow, a parametric CAD assistant. Given an engineering "
    "description of a part, write valid OFL code (the orionflow_ofl library) "
    "that produces the requested geometry."
)

VOL_TOL = 0.01


# ---------------------------------------------------------------------------
# geometry roles from the graph (the same class variant_generator accepts)
# ---------------------------------------------------------------------------

def derive_roles(g: dict) -> dict:
    """Extract od / thickness / bores / rings straight from the graph."""
    feats = g["features"]
    sketches = {s["id"]: s for s in g["sketches"]}
    pad = next(f for f in feats if f["type"] == "Pad")
    pad_sketch = sketches[feats[feats.index(pad) - 1]["id"]]
    outer_r = max(float(e["radius"]) for e in pad_sketch["geometry"])
    t = float(pad["parameters"]["Length"])

    bores, rings = [], []
    for i, f in enumerate(feats):
        if f["type"] != "Pocket":
            continue
        depth = float(f["parameters"]["Length"])
        through = depth >= t * 0.999
        sk = sketches[feats[i - 1]["id"]]
        center = [e for e in sk["geometry"]
                  if math.hypot(e.get("cx", 0), e.get("cy", 0)) <= 1e-6]
        ring = [e for e in sk["geometry"]
                if math.hypot(e.get("cx", 0), e.get("cy", 0)) > 1e-6]
        for e in center:
            bores.append({"dia": 2 * float(e["radius"]),
                          "through": through, "depth": depth})
        if ring:
            first = ring[0]
            dist = math.hypot(first["cx"], first["cy"])
            rings.append({
                "dia": 2 * float(first["radius"]),
                "bcd": 2 * dist,
                "count": len(ring),
                "start_deg": round(math.degrees(math.atan2(first["cy"], first["cx"])), 1),
                "through": through, "depth": depth,
            })
    return {"od": 2 * outer_r, "t": t, "bores": bores, "rings": rings}


# ---------------------------------------------------------------------------
# dual-emit: OFL code from roles
# ---------------------------------------------------------------------------

def emit_ofl(roles: dict) -> str:
    od, t = roles["od"], roles["t"]
    lines = ["from orionflow_ofl import *", ""]
    decls = [f"od = {od:g}", f"thickness = {t:g}"]
    body = ["", "part = Sketch(Plane.XY).circle(od).extrude(thickness)"]

    for i, b in enumerate(roles["bores"]):
        var = "bore_dia" if len(roles["bores"]) == 1 else f"bore{i + 1}_dia"
        decls.append(f"{var} = {b['dia']:g}")
        tail = ".through()" if b["through"] else f".to_depth({b['depth']:g})"
        body.append(f'part -= Hole({var}).at(0, 0){tail}.label("bore")')

    for i, r in enumerate(roles["rings"]):
        n = len(roles["rings"])
        dv = "bolt_dia" if n == 1 else f"ring{i + 1}_dia"
        pv = "bolt_pcd" if n == 1 else f"ring{i + 1}_pcd"
        cv = "bolt_count" if n == 1 else f"ring{i + 1}_count"
        decls += [f"{dv} = {r['dia']:g}", f"{pv} = {r['bcd']:g}", f"{cv} = {r['count']}"]
        tail = ".through()" if r["through"] else f".to_depth({r['depth']:g})"
        body.append(
            f"part -= Hole({dv}).at_circular({pv} / 2, count={cv}, "
            f"start_angle={r['start_deg']:g}){tail}.label(\"bolt_holes\")"
        )

    return "\n".join(lines + decls + body + ["", 'export(part, "part.step")'])


def ofl_volume(code: str) -> float:
    """Execute emitted OFL in-process (no export) and return the solid volume."""
    import orionflow_ofl as ofl

    ns = {"Sketch": ofl.Sketch, "Plane": ofl.Plane, "Part": ofl.Part,
          "Hole": ofl.Hole, "Axis": ofl.Axis, "export": lambda *a, **k: None}
    exec(compile(code, "<variant-ofl>", "exec"), ns)  # noqa: S102 - our own emitted code
    return float(ns["part"]._solid.volume)


# ---------------------------------------------------------------------------
# 5-level prompts from the parameter values
# ---------------------------------------------------------------------------

def prompts_for(row: dict, roles: dict, rng: random.Random) -> dict[str, str]:
    name = row["name"]
    od, t = f"{roles['od']:g}", f"{roles['t']:g}"
    bore = f"{roles['bores'][0]['dia']:g}" if roles["bores"] else None
    ring = roles["rings"][0] if roles["rings"] else None

    hole_clause = ""
    spec_holes = ""
    if ring:
        hole_clause = (f" and {ring['count']} bolt holes of {ring['dia']:g} mm "
                       f"on a {ring['bcd']:g} mm bolt circle")
        spec_holes = f", BCD={ring['bcd']:g}, N={ring['count']}, HOLE_DIA={ring['dia']:g}"
    bore_clause = f" with a {bore} mm center bore" if bore else ""

    vague = rng.choice([
        f"A {name} for a bolted connection",
        f"A {name}",
        f"A round {name.split()[-1]} for mechanical fastening",
    ])
    standard = (f"A {name}, {od} mm outer diameter, {t} mm thick"
                f"{bore_clause}{hole_clause}.")
    expert_ring = (f", {ring['count']}×⌀{ring['dia']:g} equally spaced on a "
                   f"{ring['bcd']:g} mm PCD" if ring else "")
    expert = (f"{name.title()}: OD {od} mm, thickness {t} mm"
              + (f", bore ⌀{bore}" if bore else "") + expert_ring + ".")
    conv_bore = f" over a {bore} mm opening" if bore else ""
    conv_ring = f" It needs {ring['count']} bolts." if ring else ""
    conversational = (f"I need a {name} about {od} mm across{conv_bore}, "
                      f"roughly {t} mm thick.{conv_ring}")
    spec = (f"{name.upper().replace(' ', '_')}: OD={od}, THK={t}"
            + (f", BORE={bore}" if bore else "") + spec_holes)

    return {"vague": vague, "standard": standard, "expert": expert,
            "conversational": conversational, "spec": spec}


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def run(limit: int = 0) -> dict:
    rows = [json.loads(l) for l in open(ACCEPTED, encoding="utf-8")]
    if limit:
        rows = rows[:limit]

    n_pairs = n_variants = n_ofl_fail = 0
    with open(PAIRS_OUT, "w", encoding="utf-8") as pairs, \
         open(CHAT_OUT, "w", encoding="utf-8") as chat:
        for row in rows:
            roles = derive_roles(row["feature_graph"])
            code = emit_ofl(roles)
            try:
                vol = ofl_volume(code)
            except Exception:
                n_ofl_fail += 1
                continue
            if abs(vol - row["analytic_volume_mm3"]) / row["analytic_volume_mm3"] > VOL_TOL:
                n_ofl_fail += 1
                continue

            rng = random.Random(row["id"])  # deterministic per variant
            for level, prompt in prompts_for(row, roles, rng).items():
                pairs.write(json.dumps({
                    "id": f"{row['id']}:{level}",
                    "variant_id": row["id"],
                    "master_id": row["master_id"],
                    "level": level,
                    "prompt": prompt,
                    "ofl_code": code,
                    "graph_path": f"variants/graphs/{row['id']}.json",
                    "values": row["values"],
                    "ofl_volume_mm3": round(vol, 1),
                    "analytic_volume_mm3": row["analytic_volume_mm3"],
                }) + "\n")
                chat.write(json.dumps({"messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": code},
                ]}) + "\n")
                n_pairs += 1
            n_variants += 1

    summary = {"variants_in": len(rows), "variants_emitted": n_variants,
               "ofl_validation_failures": n_ofl_fail, "pairs": n_pairs,
               "pairs_file": str(PAIRS_OUT), "chat_file": str(CHAT_OUT)}
    print(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    run(args.limit)


if __name__ == "__main__":
    main()
