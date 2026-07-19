"""Parametric variant generator — explodes gNucleus masters into validated
training variants.

Eligibility is capability-gated, not family-guessed: a master qualifies when
every sketch entity is a Circle and its features are exactly one Pad plus any
number of Pockets (Body/Sketch bookkeeping aside). For such parts the exact
solid volume is analytic:

    V = t * pi * (R_outer^2 - sum(r_i^2 * depth_i/t for each cut circle))

so every variant is accepted against ground truth, not just "it rebuilt".

Pipeline per master:
  1. parameter bindings from parameter_mapper (named param -> geometry targets)
  2. Latin-hypercube sample multipliers for the bound numeric params
  3. inject: circle radii, feature lengths, bolt-circle scaling, hole counts
  4. geometric sanity rejection in milliseconds (holes inside rim, no overlap)
  5. batch reconstruct under FreeCAD's python
  6. accept when rebuilt volume matches the analytic value within 1%

Usage (system Python):
    python -m freecad.variant_generator --attempts 40 --limit-masters 10
Outputs: freecad/variants/graphs/*.json + variants/accepted.jsonl
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Optional

from .config import PKG_DIR, ensure_dirs, find_freecad_python
from .parameter_mapper import map_parameters, parse_key_parameters

TRAINING_DIR = PKG_DIR / "training"
VARIANTS_DIR = PKG_DIR / "variants"
GRAPHS_DIR = VARIANTS_DIR / "graphs"
REBUILT_DIR = VARIANTS_DIR / "rebuilt"
RECONSTRUCT_SCRIPT = PKG_DIR / "reconstruct.py"

VOLUME_TOL = 0.01  # 1% against analytic ground truth
MIN_WALL = 1.0     # mm of material demanded between any cut and the rim
_BOOKKEEPING = {"Body", "Sketch"}

# multiplier ranges by mutation kind
RANGES = {
    "diameter": (0.6, 1.8),
    "length": (0.5, 2.0),
    "bcd": (0.7, 1.6),
}
COUNT_CHOICES = [3, 4, 5, 6, 8]


# ---------------------------------------------------------------------------
# eligibility + schema
# ---------------------------------------------------------------------------

def load_masters() -> list[dict[str, Any]]:
    return [json.load(open(f, encoding="utf-8"))
            for f in sorted(glob.glob(str(TRAINING_DIR / "sample_*.json")))]


def eligibility(sample: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Return (part_class, rejection_reason). Classes:
    - "circle_pads": N Pads + M Pockets, every sketch all-circles
    - "revolution": one Revolution of a line-segment profile, no cuts
    """
    g = sample["feature_graph"]
    ops = [f["type"] for f in g["features"] if f["type"] not in _BOOKKEEPING]

    if ops and all(op in ("Pad", "Pocket") for op in ops) and "Pad" in ops:
        for sk in g["sketches"]:
            kinds = {e["type"] for e in sk["geometry"]}
            if kinds - {"Circle"}:
                return None, f"non-circle geometry in {sk['id']}: {sorted(kinds)}"
        return "circle_pads", None

    if ops == ["Revolution"]:
        for sk in g["sketches"]:
            kinds = {e["type"] for e in sk["geometry"]}
            if kinds - {"LineSegment"}:
                return None, f"revolution profile not line-only: {sorted(kinds)}"
        return "revolution", None

    return None, f"unsupported feature mix: {ops}"


def build_schema(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """Named params with their geometry bindings and a mutation kind."""
    g = sample["feature_graph"]
    bound, _stats = map_parameters(g, sample["key_parameters"])
    schema = []
    for p in bound:
        kinds = {b["property"] for b in p["bound_to"]}
        if not p["bound_to"]:
            kind = "fixed"
        elif kinds & {"Diameter", "Radius"}:
            kind = "diameter"
        elif "Length" in kinds:
            kind = "length"
        elif "BoltCircleDiameter" in kinds:
            kind = "bcd"
        elif kinds & {"CircleCount", "Occurrences"}:
            kind = "count"
        else:  # SpanX/SpanY/CenterDistance/EdgeCount — leave untouched
            kind = "fixed"
        schema.append({**p, "kind": kind})
    return schema


# ---------------------------------------------------------------------------
# injection
# ---------------------------------------------------------------------------

def _sketch(g: dict, sid: str) -> dict:
    return next(s for s in g["sketches"] if s["id"] == sid)


def _geo(g: dict, target: str) -> dict:
    sid, geo = target.split(":geo")
    sk = _sketch(g, sid)
    return next(e for e in sk["geometry"] if e["index"] == int(geo))


def inject(graph: dict[str, Any], schema: list[dict], values: dict[str, float]) -> dict:
    """Return a new graph with *values* written through each param's bindings."""
    g = copy.deepcopy(graph)
    mutated_features: set[str] = set()

    master_total = sum(float(f["parameters"]["Length"])
                       for f in g["features"] if f["type"] == "Pad")

    for p in schema:
        if p["kind"] == "fixed" or p["name"] not in values:
            continue
        new = values[p["name"]]
        for b in p["bound_to"]:
            prop, target = b["property"], b["target"]
            if prop == "Diameter":
                _geo(g, target)["radius"] = new / 2.0
            elif prop == "Radius" and ":geo" in target:
                _geo(g, target)["radius"] = new
            elif prop == "Length" and ":geo" not in target:
                feat = next(f for f in g["features"] if f["id"] == target)
                feat["parameters"]["Length"] = new
                mutated_features.add(target)
            elif prop == "BoltCircleDiameter":
                sk = _sketch(g, target)
                old_r = max(
                    math.hypot(e.get("cx", 0), e.get("cy", 0))
                    for e in sk["geometry"]
                )
                scale = (new / 2.0) / old_r if old_r > 1e-9 else 1.0
                for e in sk["geometry"]:
                    e["cx"] = e.get("cx", 0.0) * scale
                    e["cy"] = e.get("cy", 0.0) * scale
            elif prop in ("CircleCount", "Occurrences"):
                sk = _sketch(g, target) if ":geo" not in target else None
                if sk is None:
                    continue
                ring = [e for e in sk["geometry"]
                        if math.hypot(e.get("cx", 0), e.get("cy", 0)) > 1e-6]
                if not ring:
                    continue
                first = ring[0]
                r_hole = float(first["radius"])
                dist = math.hypot(first["cx"], first["cy"])
                a0 = math.atan2(first["cy"], first["cx"])
                n = int(round(new))
                keep = [e for e in sk["geometry"] if e not in ring]
                new_ring = []
                for i in range(n):
                    a = a0 + i * 2 * math.pi / n
                    new_ring.append({
                        "index": len(keep) + i, "construction": False,
                        "type": "Circle", "radius": r_hole,
                        "cx": dist * math.cos(a), "cy": dist * math.sin(a),
                        "cz": first.get("cz", 0.0),
                    })
                sk["geometry"] = keep + new_ring

    # Through-cut coupling: pockets cut at >=1.5x the master stack height are
    # through-cuts by construction; keep them through at the new height.
    new_total = sum(float(f["parameters"]["Length"])
                    for f in g["features"] if f["type"] == "Pad")
    for f in g["features"]:
        if f["type"] == "Pocket" and f["id"] not in mutated_features:
            if float(f["parameters"].get("Length", 0)) >= 1.5 * master_total:
                f["parameters"]["Length"] = 2.0 * new_total

    # Keep the graph's named-parameter section in sync with the injected
    # values — reconstruct's parametrics layer (Params spreadsheet +
    # expressions) reads these.
    for p in g.get("parameters", []):
        if p.get("name") in values:
            new = values[p["name"]]
            p["value"] = int(round(new)) if isinstance(p.get("value"), int) else new
    return g


# ---------------------------------------------------------------------------
# fast rejection + analytic ground truth
# ---------------------------------------------------------------------------

def _sketch_z(sk: dict) -> float:
    gp = sk.get("global_placement") or {}
    pos = gp.get("pos") or [0.0, 0.0, 0.0]
    return float(pos[2])


def _pads(g: dict) -> list[dict]:
    """Every Pad with its profile sketch, base z, length, outer radius and
    inner (annulus) circles. Pads extrude upward from their sketch plane."""
    feats = g["features"]
    out = []
    for i, f in enumerate(feats):
        if f["type"] != "Pad":
            continue
        sk = _sketch(g, feats[i - 1]["id"])
        circles = [e for e in sk["geometry"] if e["type"] == "Circle"]
        rmax = max(float(e["radius"]) for e in circles)
        inner = [float(e["radius"]) for e in circles if float(e["radius"]) < rmax]
        z = _sketch_z(sk)
        out.append({"feat": f, "z": z, "len": float(f["parameters"]["Length"]),
                    "r": rmax, "inner": inner})
    return out


def _pockets(g: dict) -> list[dict]:
    feats = g["features"]
    out = []
    for i, f in enumerate(feats):
        if f["type"] != "Pocket":
            continue
        sk = _sketch(g, feats[i - 1]["id"])
        out.append({"feat": f, "sk": sk, "z": _sketch_z(sk),
                    "len": float(f["parameters"]["Length"])})
    return out


def geometric_ok(g: dict[str, Any]) -> bool:
    try:
        pads = _pads(g)
        if not pads:
            return False
        total_h = sum(p["len"] for p in pads)
        for p in pads:
            if p["len"] < 0.5 or p["r"] < 2.0:
                return False
            for ri in p["inner"]:
                if ri + MIN_WALL > p["r"]:
                    return False
        cuts = []
        for pk in _pockets(g):
            if pk["len"] <= 0:
                return False
            circles = [e for e in pk["sk"]["geometry"] if e["type"] == "Circle"]
            for e in circles:
                r = float(e["radius"])
                d = math.hypot(e.get("cx", 0.0), e.get("cy", 0.0))
                if r < 0.4:
                    return False
                # Radially each cut must be FULLY inside or FULLY outside
                # every pad it axially overlaps — partial rim clips break
                # the analytic volume.
                through = pk["len"] >= 0.9 * total_h
                for p in pads:
                    if not through and not _z_overlap(pk, p):
                        continue
                    if d - r < p["r"] + MIN_WALL and d + r > p["r"] - MIN_WALL:
                        return False
                cuts.append((float(e.get("cx", 0)), float(e.get("cy", 0)), r))
            ring = [e for e in circles
                    if math.hypot(e.get("cx", 0), e.get("cy", 0)) > 1e-6]
            if len(ring) >= 2:
                d = math.hypot(ring[0]["cx"], ring[0]["cy"])
                gap = 2 * d * math.sin(math.pi / len(ring))
                if gap < 2 * float(ring[0]["radius"]) + MIN_WALL:
                    return False
        for a in range(len(cuts)):
            for b in range(a + 1, len(cuts)):
                x1, y1, r1 = cuts[a]
                x2, y2, r2 = cuts[b]
                if math.hypot(x1 - x2, y1 - y2) < r1 + r2 + MIN_WALL:
                    return False
        return True
    except (StopIteration, KeyError, ValueError):
        return False


def _z_overlap(pocket: dict, pad: dict) -> float:
    """Axial overlap between a pocket (cutting DOWN from its sketch plane)
    and a pad's solid span."""
    lo, hi = pocket["z"] - pocket["len"], pocket["z"]
    plo, phi = pad["z"], pad["z"] + pad["len"]
    return max(0.0, min(hi, phi) - max(lo, plo))


def analytic_volume(g: dict[str, Any]) -> float:
    pads = _pads(g)
    total_h = sum(p["len"] for p in pads)
    vol = 0.0
    for p in pads:
        area = math.pi * (p["r"] ** 2 - sum(ri ** 2 for ri in p["inner"]))
        vol += area * p["len"]
    for pk in _pockets(g):
        through = pk["len"] >= 0.9 * total_h
        for e in pk["sk"]["geometry"]:
            if e["type"] != "Circle":
                continue
            r = float(e["radius"])
            d = math.hypot(e.get("cx", 0.0), e.get("cy", 0.0))
            for p in pads:
                if d + r > p["r"]:  # radially outside this pad (gate ensured full/none)
                    continue
                depth = p["len"] if through else _z_overlap(pk, p)
                vol -= math.pi * r * r * depth
    return vol


# ---------------------------------------------------------------------------
# revolution class: uniform radial/axial scaling (volume scales r^2 * a)
# ---------------------------------------------------------------------------

def inject_revolution(graph: dict, schema: list[dict], rf: float, af: float) -> dict:
    """Scale the revolve profile: local x (radial) by rf, local y (axial) by
    af. Named parameter values are updated from the SCALED geometry so
    prompts stay exact."""
    g = copy.deepcopy(graph)
    # These masters revolve about the LOCAL X axis (measured: volume scales
    # exactly as radial^2 * axial with radial = local y). So y is radial.
    for sk in g["sketches"]:
        for e in sk["geometry"]:
            if e["type"] == "LineSegment":
                e["sx"] = e["sx"] * af
                e["ex"] = e["ex"] * af
                e["sy"] = e["sy"] * rf
                e["ey"] = e["ey"] * rf
        if sk.get("bbox"):
            for k in ("xmin", "xmax", "span_x"):
                sk["bbox"][k] = sk["bbox"][k] * af
            for k in ("ymin", "ymax", "span_y"):
                sk["bbox"][k] = sk["bbox"][k] * rf

    sk_by_id = {s["id"]: s for s in g["sketches"]}
    for p in g.get("parameters", []):
        kinds = {b["property"] for b in p.get("bound_to", [])}
        tgt = p["bound_to"][0]["target"] if p.get("bound_to") else ""
        if kinds & {"Diameter", "Radius", "SpanY"}:
            p["value"] = round(float(p["value"]) * rf, 3)
        elif "EdgeLength" in kinds and ":geo" in tgt:
            sid, gidx = tgt.split(":geo")
            e = next((x for x in sk_by_id[sid]["geometry"]
                      if x["index"] == int(gidx)), None)
            if e:
                p["value"] = round(math.hypot(e["ex"] - e["sx"], e["ey"] - e["sy"]), 3)
        elif kinds & {"Length", "SpanX"}:
            p["value"] = round(float(p["value"]) * af, 3)
    return g


def revolution_ok(g: dict) -> bool:
    """Profile must stay on one side of the axis with sane sizes."""
    xs, ys = [], []
    for sk in g["sketches"]:
        for e in sk["geometry"]:
            if e["type"] == "LineSegment":
                xs += [e["sx"], e["ex"]]
                ys += [e["sy"], e["ey"]]
    if not xs:
        return False
    if min(ys) < -1e-6:  # radial coordinate crossing the revolve (X) axis
        return False
    return (max(xs) - min(xs)) >= 0.5 and (max(ys) - min(ys)) >= 0.5


# ---------------------------------------------------------------------------
# sampling + orchestration
# ---------------------------------------------------------------------------

def sample_values(schema: list[dict], n: int, seed: int) -> list[dict[str, float]]:
    from scipy.stats import qmc

    mutable = [p for p in schema if p["kind"] in RANGES]
    counts = [p for p in schema if p["kind"] == "count"]
    if not mutable:
        return []
    sampler = qmc.LatinHypercube(d=len(mutable), seed=seed)
    rows = sampler.random(n=n)
    import random
    rng = random.Random(seed)
    out = []
    for row in rows:
        vals: dict[str, float] = {}
        for u, p in zip(row, mutable):
            lo, hi = RANGES[p["kind"]]
            vals[p["name"]] = round(float(p["value"]) * (lo + u * (hi - lo)), 1)
        for p in counts:
            vals[p["name"]] = float(rng.choice(COUNT_CHOICES))
        out.append(vals)
    return out


def regen_key_parameters(schema: list[dict], values: dict[str, float]) -> str:
    lines = []
    for p in schema:
        v = values.get(p["name"], p["value"])
        if p["kind"] == "count" or isinstance(p["value"], int):
            v = int(round(float(v)))
        unit = p.get("unit") or ""
        lines.append(f"- {p['name']} = {v}{unit}")
    return "\n".join(lines)


def run(attempts: int, limit_masters: int, per_master_target: int, seed: int) -> dict:
    ensure_dirs()
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    REBUILT_DIR.mkdir(parents=True, exist_ok=True)

    masters = load_masters()
    eligible = []
    for m in masters:
        cls, _reason = eligibility(m)
        if cls:
            eligible.append((m, cls, build_schema(m)))
    if limit_masters:
        eligible = eligible[:limit_masters]
    n_by_class: dict[str, int] = {}
    for _, cls, _ in eligible:
        n_by_class[cls] = n_by_class.get(cls, 0) + 1
    print(f"[eligible] {len(eligible)}/{len(masters)} masters: {n_by_class}")

    # Master volumes from the last full rebuild — ground truth scale base
    # for the revolution class.
    try:
        master_vol = {r["source_id"]: r.get("volume")
                      for r in json.loads(
                          (PKG_DIR / "rebuilt" / "_reports.json").read_text(encoding="utf-8"))}
    except OSError:
        master_vol = {}

    # Phase A: sample + inject + fast-reject; collect candidates
    manifest, candidates = [], {}
    for m, cls, schema in eligible:
        kept = 0
        if cls == "circle_pads":
            for k, vals in enumerate(sample_values(schema, attempts, seed)):
                if kept >= per_master_target:
                    break
                g = inject(m["feature_graph"], schema, vals)
                if not geometric_ok(g):
                    continue
                vid = f"{m['id']}_v{k:03d}"
                g["source_id"] = vid  # reports key on the graph's own id
                gp = GRAPHS_DIR / f"{vid}.json"
                gp.write_text(json.dumps(g), encoding="utf-8")
                manifest.append({"id": vid, "graph": str(gp)})
                candidates[vid] = {"master": m, "schema": schema, "values": vals,
                                   "analytic": analytic_volume(g)}
                kept += 1
        else:  # revolution: sample radial/axial scale factors
            v0 = master_vol.get(m["id"])
            if not v0:
                print(f"  {m['id']}: no master volume, skipped")
                continue
            from scipy.stats import qmc
            rows = qmc.LatinHypercube(d=2, seed=seed).random(n=attempts)
            for k, (u1, u2) in enumerate(rows):
                if kept >= per_master_target:
                    break
                rf = 0.6 + u1 * 1.0
                af = 0.6 + u2 * 1.0
                g = inject_revolution(m["feature_graph"], schema, rf, af)
                if not revolution_ok(g):
                    continue
                vid = f"{m['id']}_v{k:03d}"
                g["source_id"] = vid
                gp = GRAPHS_DIR / f"{vid}.json"
                gp.write_text(json.dumps(g), encoding="utf-8")
                manifest.append({"id": vid, "graph": str(gp)})
                vals = {p["name"]: p["value"] for p in g.get("parameters", [])}
                candidates[vid] = {"master": m, "schema": schema, "values": vals,
                                   "analytic": float(v0) * rf * rf * af}
                kept += 1
        print(f"  {m['id']} ({m['name'][:34]}) [{cls}]: {kept} candidates")

    if not manifest:
        return {"eligible": len(eligible), "accepted": 0}

    # Phase B: batch reconstruct under FreeCAD python
    mp = REBUILT_DIR / "_manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    print(f"[compile] {len(manifest)} candidates -> FreeCAD")
    proc = subprocess.run(
        [find_freecad_python(), str(RECONSTRUCT_SCRIPT),
         "--manifest", str(mp), "--out-dir", str(REBUILT_DIR)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("reconstruct failed:\n" + (proc.stderr or "")[-1200:])
    reports = {r["source_id"]: r
               for r in json.loads((REBUILT_DIR / "_reports.json").read_text(encoding="utf-8"))}

    # Phase C: accept against analytic ground truth
    accepted, rejected = [], 0
    out_path = VARIANTS_DIR / "accepted.jsonl"
    with open(out_path, "w", encoding="utf-8") as out:
        for vid, c in candidates.items():
            rep = reports.get(vid) or {}
            vol = rep.get("volume")
            ok = (
                rep.get("doc_recomputed")
                and not rep.get("recompute_errors")
                and vol and c["analytic"] > 0
                and abs(vol - c["analytic"]) / c["analytic"] <= VOLUME_TOL
            )
            if not ok:
                rejected += 1
                continue
            m = c["master"]
            row = {
                "id": vid,
                "master_id": m["id"],
                "name": m["name"],
                "description": m["description"],
                "key_parameters": regen_key_parameters(c["schema"], c["values"]),
                "values": c["values"],
                "volume_mm3": round(vol, 1),
                "analytic_volume_mm3": round(c["analytic"], 1),
                "feature_graph": json.loads((GRAPHS_DIR / f"{vid}.json").read_text(encoding="utf-8")),
            }
            out.write(json.dumps(row) + "\n")
            accepted.append(vid)

    summary = {"eligible_masters": len(eligible), "candidates": len(manifest),
               "accepted": len(accepted), "rejected": rejected,
               "out": str(out_path)}
    print(f"[done] {json.dumps(summary, indent=1)}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempts", type=int, default=40, help="LHS samples per master")
    ap.add_argument("--per-master", type=int, default=25, help="max candidates per master")
    ap.add_argument("--limit-masters", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    run(args.attempts, args.limit_masters, args.per_master, args.seed)


if __name__ == "__main__":
    main()
