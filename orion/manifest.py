"""One declarative record of what exists: models, datasets, families.

Versions were accumulating in commit messages and conversation rather than
anywhere a program could read. This is the registry — every model checkpoint,
every dataset, and every procedural family with the engineering concepts it
covers.

The coverage field is the important one. The measured lesson of v1 -> v2 is that
*diversity of concept* beats *quantity of sample*: 95.3% on held-out topologies
collapsed to 50% on free-form prose because one prompt skeleton had been sampled
25,000 times. The same trap applies to mechanisms — four assembly families
sampled 8,000 times is still four mechanisms. So families are tracked by the
engineering concepts they teach, not by how many rows they can produce.

    python -m orion.manifest            # print the registry and what is on disk
"""

from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #
MODELS = {
    "v1": {
        "base": "Qwen/Qwen3-32B",
        "method": "LoRA r=64 alpha=128 bf16, 1 epoch, 1471 steps",
        "dataset": "sft_v1",
        "artifact": "sahilmaniyar888/orionflow-cad-qwen3-32b-lora (private HF)",
        "status": "complete",
        "scores": {
            "verified_heldout_topology": 0.953,
            "verified_at_1_repair": 0.963,
            "view_spec": 0.988,
            "view_design_synthetic_prose": 0.912,
            "free_form_prose": 0.50,
            "volume_rel_err_median": 1.94e-16,
        },
        "known_limits": [
            "states volumes it never evaluates (0/229 correct) — its real "
            "prediction is the expression, which is exact",
            "cannot repair a guard violation even when handed the arithmetic",
            "50% on free engineering prose: one prompt skeleton in training",
        ],
    },
    "v2": {
        "base": "Qwen/Qwen3-32B",
        "method": "LoRA r=64 alpha=128 bf16, 1 epoch, 1471 steps",
        "dataset": "sft_v2",
        "artifact": "sahilmaniyar888/orionflow-cad-qwen3-32b-lora, v2/ "
                    "(private HF)",
        "status": "complete",
        "scores": {
            "verified_heldout_topology": 0.940,
            "view_spec": 0.911,
            "view_design_synthetic_prose": 0.944,
            "free_form_prose": 0.58,
            "volume_rel_err_median": 2.05e-16,
        },
        "known_limits": [
            "in-distribution accuracy flat vs v1 (94.0 vs 95.3, within noise); "
            "the gain is in prose robustness, which was the objective",
            "remaining failures are engineering judgement, not language: "
            "12 wrong volume derivations, 4 self-violated preconditions",
            "eval loss bottomed at step 400 and rose to 0.0776 while quality "
            "held — early stopping on it would again ship a worse model",
        ],
    },
}

# --------------------------------------------------------------------------- #
# datasets
# --------------------------------------------------------------------------- #
DATASETS = {
    "sft_v1": {
        "path": "data/forge/sft_v1",
        "target": "Blueprint (single part)",
        "samples": 25560,
        "prompt_views": {"spec": 0.5, "design_synthetic": 0.5},
        "note": "one prose skeleton — the cause of the free-form collapse",
    },
    "sft_v2": {
        "path": "data/forge/sft_v2",
        "target": "Blueprint (single part)",
        "samples": 25560,
        "prompt_views": {"spec": 0.15, "design_synthetic": 0.10,
                         "diverse_real_world": 0.75},
        "note": "same geometry as v1; only the phrasing distribution changed",
    },
    "gears_v3": {
        "path": "data/forge/gears",
        "target": "Blueprint (involute spur gear)",
        "note": "needed a new assertion kind, body_volume_profile, because an "
                "involute has no closed form in the expression language",
    },
    "asm_v3": {
        "path": "data/forge/asm_v1",
        "target": "AssemblySpec (components + mates + assertions)",
        "note": "no transforms in the target — placement is derived, because "
                "loop closure is arithmetic the model cannot do",
    },
}

# --------------------------------------------------------------------------- #
# procedural families, by the engineering concept each one teaches
# --------------------------------------------------------------------------- #
FAMILIES = {
    # components
    "hex_bolt":        {"tier": "fastener", "concepts": ["ISO 4014 head geometry", "thread as data", "grip length"]},
    "hex_nut":         {"tier": "fastener", "concepts": ["tapping bore", "across-flats"]},
    "washer":          {"tier": "fastener", "concepts": ["load spreading"]},
    "clearance_plate": {"tier": "structure", "concepts": ["ISO 273 clearance", "edge distance"]},
    "bearing_ring":    {"tier": "bearing", "concepts": ["annular section", "raceway space"]},
    "bearing_shaft":   {"tier": "shaft", "concepts": ["locating shoulder", "seat diameter"]},
    "link_bar":        {"tier": "linkage", "concepts": ["pin centres", "pin land"]},
    "spur_gear":       {"tier": "gear", "concepts": ["involute flank", "ISO 53 rack", "undercut limit", "module"]},
    # assemblies
    "bolted_joint":    {"tier": "fastener", "concepts": ["stack-up", "thread engagement", "ISO 898-1 torque", "preload"]},
    "bearing_stack":   {"tier": "bearing", "concepts": ["k6/H7 interference as tolerance not geometry", "axial location"]},
    "four_bar_linkage": {"tier": "motion", "concepts": ["loop closure", "Grashof classification", "change point"]},
    "flat_pulley":     {"tier": "belt", "concepts": ["pitch diameter", "rim section"]},
    "belt_drive":      {"tier": "belt", "concepts": ["speed ratio", "open-belt pitch length", "wrap angle", "slip limit", "centre distance tensioning"]},
    "lead_screw":      {"tier": "screw", "concepts": ["ISO 2904 trapezoidal", "mean diameter"]},
    "screw_nut":       {"tier": "screw", "concepts": ["thread engagement length", "bronze nut wall"]},
    "lead_screw_drive": {"tier": "screw", "concepts": ["lead vs pitch", "helix angle", "self-locking", "efficiency tradeoff", "slenderness/buckling", "revs per travel"]},
    "compression_spring": {"tier": "spring", "concepts": ["spring index", "rate (d^4 law)", "solid height", "Wahl curvature factor", "buckling slenderness"]},
    "spring_plunger":  {"tier": "spring", "concepts": ["preload force", "force at stroke", "coil clash", "stiffness not shape"]},
    "parallel_key":    {"tier": "keyed", "concepts": ["DIN 6885 sizing"]},
    "keyed_shaft":     {"tier": "keyed", "concepts": ["milled keyseat open at OD", "segment-exact removal"]},
    "keyed_hub":       {"tier": "keyed", "concepts": ["broached keyway", "wall over keyway"]},
    "keyed_coupling":  {"tier": "keyed", "concepts": ["shear vs bearing capacity", "bearing governs", "stress-based sizing"]},
    "planetary_stage": {"tier": "gear", "concepts": ["centre distance", "assembly condition", "Willis ratio", "planet clearance", "redundant planets"]},
}

#: families worth building next, in the order their concepts are missing
ROADMAP = [
    ("sheet_bracket",  ["bend allowance", "K-factor", "flat pattern", "bend relief"]),
    ("harmonic_drive", ["flexspline", "wave generator", "tooth differential ratio"]),
    ("robot_joint",    ["actuator + reducer + bearing stack", "torque path"]),
]


def on_disk() -> dict:
    """Count what actually exists, rather than what is declared."""
    out = {}
    for name, d in DATASETS.items():
        p = os.path.join(ROOT, d["path"])
        n = 0
        if os.path.isdir(p):
            for fn in os.listdir(p):
                if fn.endswith(".jsonl"):
                    with open(os.path.join(p, fn), encoding="utf-8") as fh:
                        n += sum(1 for _ in fh)
        out[name] = n
    return out


def main() -> None:
    counts = on_disk()
    print("MODELS")
    for k, m in MODELS.items():
        s = m.get("scores", {})
        head = (f"verified {s['verified_heldout_topology']:.1%}"
                if s.get("verified_heldout_topology") else m["status"])
        print(f"  {k:4s} {m['status']:9s} {head}")
        if s.get("free_form_prose"):
            print(f"       free-form prose {s['free_form_prose']:.0%} "
                  "<- the number that matters for real use")
    print("\nDATASETS (rows on disk)")
    for k, d in DATASETS.items():
        print(f"  {k:10s} {counts.get(k, 0):7,}  {d['target']}")
    print("\nFAMILIES BY TIER")
    tiers: dict[str, list[str]] = {}
    for name, f in FAMILIES.items():
        tiers.setdefault(f["tier"], []).append(name)
    for t, names in sorted(tiers.items()):
        print(f"  {t:10s} {', '.join(sorted(names))}")
    concepts = {c for f in FAMILIES.values() for c in f["concepts"]}
    print(f"\n  {len(FAMILIES)} families covering {len(concepts)} "
          "distinct engineering concepts")
    print("\nROADMAP (missing concepts, in priority order)")
    for name, cs in ROADMAP:
        print(f"  {name:20s} {', '.join(cs)}")


if __name__ == "__main__":
    main()
