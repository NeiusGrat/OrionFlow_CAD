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
from typing import Optional

from .config import PKG_DIR

VARIANTS_DIR = PKG_DIR / "variants"
ACCEPTED = VARIANTS_DIR / "accepted.jsonl"
PAIRS_OUT = VARIANTS_DIR / "training_pairs.jsonl"
CHAT_OUT = VARIANTS_DIR / "ofl_chat.jsonl"
FG_CHAT_OUT = VARIANTS_DIR / "fg_chat.jsonl"

SYSTEM_PROMPT = (
    "You are OrionFlow, a parametric CAD assistant. Given an engineering "
    "description of a part, write valid OFL code (the orionflow_ofl library) "
    "that produces the requested geometry."
)

FG_SYSTEM_PROMPT = (
    "You are OrionFlow, a parametric CAD assistant. Given an engineering "
    "description of a part, emit a FeatureGraph JSON object (schema "
    "ofl_fcstd_v1) that compiles to a native FreeCAD PartDesign feature "
    "tree: features (Sketch/Pad/Pocket/Revolution with parameters), "
    "sketches (plane + geometry), and named parameters."
)


def graph_for_training(g: dict) -> dict:
    """Slim the graph to what the model must learn to emit — drop derived
    view data (bbox, resolved placements) the compiler can live without."""
    out = {
        "schema_version": g.get("schema_version", "ofl_fcstd_v1"),
        "features": g.get("features", []),
        "sketches": [
            {k: v for k, v in sk.items()
             if k in ("id", "plane", "z", "geometry")}
            for sk in g.get("sketches", [])
        ],
        "dependencies": g.get("dependencies", []),
        "parameters": [
            {k: v for k, v in p.items() if k in ("name", "value", "unit")}
            for p in g.get("parameters", [])
        ],
    }
    return out

VOL_TOL = 0.01


# ---------------------------------------------------------------------------
# geometry roles from the graph (the same class variant_generator accepts)
# ---------------------------------------------------------------------------

def derive_roles(g: dict) -> Optional[dict]:
    """Extract pads / bores / rings straight from the graph. Returns None for
    part classes OFL cannot express (Revolution, annulus pads)."""
    feats = g["features"]
    if any(f["type"] == "Revolution" for f in feats):
        return None
    sketches = {s["id"]: s for s in g["sketches"]}

    pads = []
    for i, f in enumerate(feats):
        if f["type"] != "Pad":
            continue
        sk = sketches[feats[i - 1]["id"]]
        circles = [e for e in sk["geometry"] if e["type"] == "Circle"]
        rmax = max(float(e["radius"]) for e in circles)
        if any(float(e["radius"]) < rmax for e in circles):
            return None  # annulus profile — no OFL equivalent yet
        gp = sk.get("global_placement") or {}
        z = float((gp.get("pos") or [0, 0, 0])[2])
        pads.append({"d": 2 * rmax, "len": float(f["parameters"]["Length"]), "z": z})
    if not pads:
        return None
    pads.sort(key=lambda p: p["z"])
    total_h = sum(p["len"] for p in pads)

    t = total_h  # through-detection threshold spans the whole stack

    bores, rings = [], []
    for i, f in enumerate(feats):
        if f["type"] != "Pocket":
            continue
        depth = float(f["parameters"]["Length"])
        through = depth >= t * 0.9
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
    if any(not b["through"] for b in bores) and len(pads) > 1:
        return None  # blind cuts in a stack — OFL depth semantics differ
    return {"pads": pads, "od": pads[0]["d"], "t": total_h,
            "bores": bores, "rings": rings}


# ---------------------------------------------------------------------------
# dual-emit: OFL code from roles
# ---------------------------------------------------------------------------

def emit_ofl(roles: dict) -> str:
    pads = roles["pads"]
    lines = ["from orionflow_ofl import *", ""]
    if len(pads) == 1:
        decls = [f"od = {pads[0]['d']:g}", f"thickness = {pads[0]['len']:g}"]
        body = ["", "part = Sketch(Plane.XY).circle(od).extrude(thickness)"]
    else:
        decls, body = [], [""]
        z0 = pads[0]["z"]
        for i, p in enumerate(pads, start=1):
            decls += [f"d{i} = {p['d']:g}", f"h{i} = {p['len']:g}"]
            off = p["z"] - z0
            sk = (f"Sketch(Plane.XY, offset={off:g})" if off > 1e-6
                  else "Sketch(Plane.XY)")
            if i == 1:
                body.append(f"part = {sk}.circle(d1).extrude(h1)")
            else:
                body.append(f"part += {sk}.circle(d{i}).extrude(h{i})")

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

def prompts_from_values(row: dict, rng: random.Random) -> dict[str, str]:
    """Parameter-table prompts for classes without OFL role extraction
    (revolved pins, stepped shafts...). Still exact by construction."""
    name = row["name"].replace("_", " ")
    vals = [(k.replace("_", " "), v) for k, v in (row.get("values") or {}).items()]

    def _fmt(k: str, v) -> str:
        if not isinstance(v, float):
            return f"{k} {v}"
        unit = "°" if "angle" in k else " mm"
        return f"{k} {v}{unit}"

    plist = ", ".join(_fmt(k, v) for k, v in vals)
    spec = ", ".join(f"{k.upper().replace(' ', '_')}={v}" for k, v in vals)
    lead = vals[0] if vals else ("size", "")
    return {
        "vague": rng.choice([f"A {name}", f"A standard {name}",
                             f"A {name} for a mechanical assembly"]),
        "standard": f"A {name} with {plist}.",
        "expert": f"{name.title()} per spec: {plist}.",
        "conversational": (f"I need a {name} — roughly {lead[0]} {lead[1]}, "
                           "standard proportions otherwise."),
        "spec": f"{name.upper().replace(' ', '_')}: {spec}",
    }


def prompts_for(row: dict, roles: dict, rng: random.Random) -> dict[str, str]:
    name = row["name"]
    if len(roles.get("pads", [])) > 1:
        steps = "; ".join(f"⌀{p['d']:g}×{p['len']:g} mm" for p in roles["pads"])
        base = prompts_from_values(row, rng)
        base["standard"] = f"A {name} with {len(roles['pads'])} sections: {steps}."
        return base
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

    n_pairs = n_fg = n_variants = n_ofl_fail = 0
    with open(PAIRS_OUT, "w", encoding="utf-8") as pairs, \
         open(CHAT_OUT, "w", encoding="utf-8") as chat, \
         open(FG_CHAT_OUT, "w", encoding="utf-8") as fg_chat:
        for row in rows:
            roles = derive_roles(row["feature_graph"])
            code = None
            if roles is not None:
                code = emit_ofl(roles)
                try:
                    vol = ofl_volume(code)
                    if abs(vol - row["analytic_volume_mm3"]) / row["analytic_volume_mm3"] > VOL_TOL:
                        raise ValueError("volume mismatch")
                except Exception:
                    n_ofl_fail += 1
                    code = None

            fg_json = json.dumps(graph_for_training(row["feature_graph"]),
                                 separators=(",", ":"))
            rng = random.Random(row["id"])  # deterministic per variant
            prompts = (prompts_for(row, roles, rng) if roles and code
                       else prompts_from_values(row, rng))
            for level, prompt in prompts.items():
                pairs.write(json.dumps({
                    "id": f"{row['id']}:{level}",
                    "variant_id": row["id"],
                    "master_id": row["master_id"],
                    "level": level,
                    "prompt": prompt,
                    "ofl_code": code,
                    "graph_path": f"variants/graphs/{row['id']}.json",
                    "values": row["values"],
                    "analytic_volume_mm3": row["analytic_volume_mm3"],
                }) + "\n")
                fg_chat.write(json.dumps({"messages": [
                    {"role": "system", "content": FG_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": fg_json},
                ]}) + "\n")
                n_fg += 1
                if code:
                    chat.write(json.dumps({"messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": code},
                    ]}) + "\n")
                    n_pairs += 1
            n_variants += 1

    summary = {"variants_in": len(rows), "variants_emitted": n_variants,
               "ofl_skipped_or_failed": n_ofl_fail,
               "ofl_pairs": n_pairs, "fg_pairs": n_fg,
               "pairs_file": str(PAIRS_OUT), "chat_file": str(CHAT_OUT),
               "fg_chat_file": str(FG_CHAT_OUT)}
    print(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    run(args.limit)


if __name__ == "__main__":
    main()
