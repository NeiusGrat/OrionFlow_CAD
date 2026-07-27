"""Pack verified assemblies into training rows.

The authored target is the AssemblySpec *without transforms*: which components
(family + parameters), how they relate (mates), and what must be true
(assertions). Placement is derived by the harness, not generated, for the same
reason volumes are not generated — a four-bar's joint positions come from
circle intersection, and a model that cannot multiply reliably has no business
emitting them. Relationships are the authored content; transforms follow.

    python -m orion.pack_assembly --n 30 --out data/forge/asm_v1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor

from .assembly import build_assembly
from .assembly_spec import (bearing_stack, belt_drive, bolted_joint,
                            four_bar, keyed_coupling,
                            lead_screw_drive, planetary_stage_spec,
                            resolve_spec, spring_plunger)
from .prompt_styles import build_prompt

SYSTEM_PROMPT = (
    "You are OrionFlow, a mechanical design engine. Given an engineering "
    "request you produce a parametric AssemblySpec: named variables, the "
    "components drawn from the standard family catalogue with their "
    "parameters as expressions over those variables, the mates that relate "
    "them, and the assertions that prove the assembly is correct — clearances, "
    "fits, engagement, and non-interference.\n"
    "Reason through the engineering inside <think>...</think>, then emit the "
    "AssemblySpec as a single JSON object and nothing else."
)


def authored_target(spec: dict) -> dict:
    """The part of the spec a model should write: intent and relationships."""
    return {
        "assembly_class": spec["assembly_class"],
        "variables": spec["variables"],
        "components": [{"id": c["id"], "family": c["family"],
                        "params": c["params"], "process": c.get("process")}
                       for c in spec["components"]],
        "mates": spec["mates"],
        "assertions": spec["assertions"],
    }


def think_block(spec: dict, verdict: dict, motion: dict | None) -> str:
    """The engineering reasoning, ending in the checks that were proven."""
    v = spec["variables"]
    lines = []
    cls = spec["assembly_class"]
    if cls == "bolted_joint":
        lines += [
            f"grip = 2*plate_t = {v['grip']:g} mm through both members",
            f"bolt length must cover grip + washer + nut + 2 pitches = "
            f"{v['grip'] + v['washer_t'] + v['nut_h'] + 2 * v['pitch']:g}, "
            f"rounded up to the next stock length {v['length']:g}",
            f"clearance hole r = (d+1)/2 = {v['hole_r']:g} (ISO 273 normal)",
            f"tightening torque = K*F*d at 65% proof, class 8.8 -> "
            f"{v['torque_nm']:.1f} Nm",
        ]
    elif cls == "bearing_stack":
        lines += [
            f"bore {v['bore']:g} sets the shaft seat radius {v['r_seat']:g}",
            "inner ring is nominally tangent to the seat — the interference is "
            "a tolerance (shaft k6 / bore H7), not overlapping geometry",
            f"ring section {v['ring_t']:g} and ball space {v['ball_gap']:g} "
            f"give outside radius {v['r_outer_out']:g}",
            "the shaft shoulder locates the inner ring axially",
        ]
    elif cls == "four_bar_linkage":
        lines += [
            f"links: ground {v['ground']:g}, crank {v['crank']:g}, "
            f"coupler {v['coupler']:g}, rocker {v['rocker']:g}",
            f"Grashof: s+l = {v['s'] + v['l']:g} vs p+q = {v['p'] + v['q']:g} "
            f"-> {'crank-rocker, the crank fully rotates' if v['s'] + v['l'] <= v['p'] + v['q'] else 'double-rocker'}",
            "coupler/rocker joint is the intersection of a circle of radius "
            "coupler about the crank pin with one of radius rocker about the "
            "fixed pivot — solved by the harness, not stated here",
            "links sit on separate Z layers so the pins align and the bars "
            "never share space",
        ]
    elif cls == "keyed_coupling":
        lines += [
            f"DIN 6885 sets the key section from the shaft: {v['b']:g}x{v['h']:g}",
            f"shear capacity  = tau*b*L*d/2 = {v['capacity_shear_nm']:.0f} Nm",
            f"bearing capacity = sig*(h/2)*L*d/2 = "
            f"{v['capacity_bearing_nm']:.0f} Nm",
            f"bearing governs -> {v['capacity_nm']:.0f} Nm against a duty of "
            f"{v['torque_nm']:.0f} Nm; only half the key height bears on the "
            "hub, so sizing against shear overstates capacity roughly 2x",
            "the keyseat is milled OPEN at the shaft OD, so its section is the "
            "slot rectangle intersected with the round shaft, not b*(h/2)",
        ]
    elif cls == "spring_plunger":
        lines += [
            f"spring index C = D/d = {v['spring_index']:.1f} (4-12 is coilable)",
            f"rate k = G*d^4/(8*D^3*Na) = {v['rate_n_per_mm']:.2f} N/mm — the "
            "FOURTH power of wire diameter dominates the design",
            f"preload {v['preload_mm']:g} mm gives {v['force_preload_n']:.1f} N; "
            f"at full {v['stroke']:g} mm stroke {v['force_max_n']:.1f} N",
            f"solid height d*(Na+2) = {v['solid_length']:.1f} mm; working "
            f"length at full stroke {v['working_len']:.1f} mm, so the coils "
            "never clash",
            "two springs of identical wire and coil diameter behave "
            "differently if Na differs — the geometry does not show it",
        ]
    elif cls == "lead_screw_drive":
        lines += [
            f"Tr{v['d']:g}x{v['pitch']:g}"
            + (f", {int(v['starts'])} starts" if v['starts'] > 1 else "")
            + f" -> lead = pitch*starts = {v['lead']:g} mm/rev",
            f"helix angle lambda = atan(lead/(pi*dm)) = {v['helix_deg']:.2f} deg",
            ("tan(lambda) < mu (0.15): the screw SELF-LOCKS and holds load "
             "without a brake" if v['self_locking'] else
             "tan(lambda) > mu (0.15): the screw BACK-DRIVES under load and "
             "needs a brake to hold position"),
            f"efficiency eta = tan(l)/tan(l+phi) = {v['efficiency']:.1%} — "
            "self-locking and efficiency trade directly against each other",
            f"{v['revs_per_travel']:.0f} revolutions for {v['travel']:g} mm of "
            "travel",
        ]
    elif cls == "belt_drive":
        lines += [
            f"speed ratio i = d2/d1 = {v['ratio']:.3f}:1",
            f"open-belt pitch length L = 2C + pi*(d1+d2)/2 + (d2-d1)^2/(4C) "
            f"= {v['belt_length']:.1f} mm",
            f"wrap on the small pulley = pi - 2*asin((d2-d1)/(2C)) = "
            f"{v['wrap_small_deg']:.1f} deg — below ~120 a friction belt slips "
            "before it transmits rated torque",
            "the belt is specified, not modelled: it is meant to touch both "
            "pulleys, so modelling it would void the non-interference proof",
        ]
    elif cls == "planetary_stage":
        r = motion["ratios"] if motion else {}
        lines += [
            f"centre distance a = m*(z_sun+z_planet)/2 = {v['a']:g} mm",
            f"ring teeth z_ring = z_sun + 2*z_planet = {int(v['z_ring'])}",
            f"assembly condition (z_sun+z_ring)/n = "
            f"{(v['z_sun'] + v['z_ring']) / v['n_planets']:g} must be an integer",
            f"ratio with the ring held = 1 + z_ring/z_sun = "
            f"{r.get('ring_fixed_sun_in_carrier_out', 0)}:1",
        ]
    passed = [a["id"] for a in verdict.get("assertions", []) if a["passed"]]
    lines.append("proven: " + ", ".join(passed))
    return "\n".join(lines)


def sample_params(cls: str, rng: random.Random) -> dict:
    if cls == "bolted_joint":
        return dict(d=rng.choice([6.0, 8.0, 10.0, 12.0, 16.0]),
                    plate_t=rng.choice([6.0, 8.0, 10.0, 12.0, 16.0, 20.0]),
                    n_bolts=2, cls=rng.choice(["8.8", "10.9", "12.9"]))
    if cls == "bearing_stack":
        return dict(bore=rng.choice([20.0, 25.0, 30.0, 35.0, 40.0, 50.0]),
                    ring_t=rng.choice([5.0, 6.0, 8.0]),
                    ball_gap=rng.choice([3.0, 4.0, 5.0, 6.0]),
                    width=rng.choice([10.0, 12.0, 14.0, 18.0]),
                    shaft_len=rng.choice([50.0, 60.0, 70.0, 90.0]))
    if cls == "four_bar_linkage":
        return dict(ground=rng.choice([90.0, 100.0, 120.0, 140.0]),
                    crank=rng.choice([25.0, 30.0, 35.0, 40.0]),
                    coupler=rng.choice([80.0, 90.0, 100.0, 110.0]),
                    rocker=rng.choice([60.0, 70.0, 80.0, 90.0]),
                    theta_deg=rng.choice([45.0, 60.0, 75.0, 90.0, 120.0]),
                    link_w=rng.choice([16.0, 18.0, 22.0]),
                    link_t=rng.choice([5.0, 6.0, 8.0]))
    if cls == "keyed_coupling":
        from .families import key_capacity
        shaft_d = rng.choice([20.0, 25.0, 30.0, 35.0, 40.0, 50.0])
        hub_len = round(rng.uniform(1.3, 1.8) * shaft_d, 0)
        cap = key_capacity(shaft_d, hub_len)
        # duty torque inside the band the assertions allow: carried, not
        # grossly oversized
        duty = round(cap["torque_nm"] * rng.uniform(0.35, 0.85), 0)
        return dict(shaft_d=shaft_d, hub_od=round(shaft_d * 2.0, 0),
                    hub_len=hub_len, shaft_len=round(hub_len + 45.0, 0),
                    torque_nm=duty)
    if cls == "spring_plunger":
        # Sample from the FEASIBLE region rather than guessing and being
        # rejected. Two constraints bound free length from opposite sides:
        # buckling caps it at 2.6*D, and the allowable shear at solid caps the
        # deflection the wire can take. Earlier blind sampling passed 1/10.
        from .families import SPRING_MATERIALS
        wire_d = rng.choice([1.6, 2.0, 2.5, 3.0, 4.0])
        coil_d = wire_d * rng.choice([6.0, 7.0, 8.0, 9.0, 10.0])
        n_active = rng.choice([6.0, 7.0, 8.0, 9.0, 10.0])
        solid = wire_d * (n_active + 2)
        mat = SPRING_MATERIALS["music_wire_astm_a228"]
        c = coil_d / wire_d
        kw = (4 * c - 1) / (4 * c - 4) + 0.615 / c
        rate = mat["G"] * wire_d ** 4 / (8.0 * coil_d ** 3 * n_active)
        # deflection at which the corrected shear reaches 80% of allowable
        defl_max = (0.8 * mat["tau_allow"] * math.pi * wire_d ** 3
                    / (kw * 8.0 * rate * coil_d))
        free_len = round(min(2.5 * coil_d, solid + defl_max), 0)
        usable = free_len - solid
        if usable < 6:
            return None
        stroke = round(usable * 0.5, 0)
        # plunger must leave a real shoulder against the spring seat: the
        # bearing_shaft family needs r_seat - r_shaft - 1 > 0, and an earlier
        # formula made that identically zero for every sample.
        return dict(wire_d=wire_d, coil_d=coil_d, n_active=n_active,
                    free_len=free_len,
                    plunger_d=round(coil_d - wire_d - 7, 1),
                    bore_d=round(coil_d + wire_d + 4, 1),
                    preload_mm=round(stroke * 0.4, 1), stroke=stroke)
    if cls == "lead_screw_drive":
        from .families import ISO_TRAPEZOIDAL
        d = rng.choice([12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 30.0])
        starts = rng.choice([1, 1, 1, 2, 4])       # single-start dominates
        travel = rng.choice([100.0, 150.0, 200.0, 250.0, 300.0])
        nut_len = round(max(1.6 * d, 25.0), 0)
        return dict(d=d, starts=starts, travel=travel, nut_len=nut_len,
                    length=travel + nut_len + rng.choice([30.0, 50.0, 80.0]),
                    nut_od=round(d + ISO_TRAPEZOIDAL[d] * 2 + 12.0, 0))
    if cls == "belt_drive":
        d1 = rng.choice([56.0, 63.0, 71.0, 80.0, 90.0, 100.0])
        # keep the ratio inside what a single friction-belt stage does well
        d2 = d1 * rng.choice([1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
        return dict(d1=d1, d2=d2,
                    centres=round(rng.uniform(1.2, 2.2) * (d1 + d2), 0),
                    width=rng.choice([16.0, 20.0, 25.0, 32.0]),
                    bore1=rng.choice([14.0, 19.0, 24.0]),
                    bore2=rng.choice([19.0, 24.0, 28.0]))
    if cls == "planetary_stage":
        # Combos are DERIVED from the shared gear rules plus the planetary
        # assembly condition, rather than hand-listed. Hand-listing is what put
        # 15-, 16- and 21-tooth gears into the sampler three separate times.
        from .gear_family import even_teeth_choices
        zs_all = even_teeth_choices(hi=36)
        combos = [(zs, zp, n)
                  for zs in zs_all for zp in zs_all for n in (3, 4)
                  if (zs + (zs + 2 * zp)) % n == 0 and zp <= zs]
        combo = rng.choice(combos)
        return dict(module=rng.choice([1.5, 2.0, 2.5]),
                    z_sun=combo[0], z_planet=combo[1], n_planets=combo[2],
                    face_width=rng.choice([10.0, 12.0, 15.0]),
                    sun_bore=rng.choice([6.0, 8.0, 10.0]),
                    planet_bore=rng.choice([4.0, 5.0, 6.0]))
    raise KeyError(cls)


BUILDERS = {
    "bolted_joint": bolted_joint,
    "bearing_stack": bearing_stack,
    "four_bar_linkage": four_bar,
    "planetary_stage": planetary_stage_spec,
    "belt_drive": belt_drive,
    "lead_screw_drive": lead_screw_drive,
    "spring_plunger": spring_plunger,
    "keyed_coupling": keyed_coupling,
}


def make_spec(cls: str, params: dict):
    """Every class is now a family-reference spec, so packing is uniform and
    every assembly carries its mate graph."""
    spec = BUILDERS[cls](**params)
    return spec, (resolve_spec(spec) if spec else None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--out", default="data/forge/asm_v1")
    ap.add_argument("--seed", type=int, default=1602)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--classes", default="bolted_joint,bearing_stack,"
                                         "four_bar_linkage,planetary_stage,"
                                         "belt_drive,lead_screw_drive,spring_plunger,"
                                         "keyed_coupling")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    workdir = os.path.abspath(args.out)
    rng = random.Random(args.seed)
    classes = args.classes.split(",")

    # Sample every parameter set BEFORE building. A worker pool needs the work
    # list up front, and — less obviously — this decouples sampling from build
    # outcomes. Sharing one rng between sampling and prompt generation made a
    # failure's parameters depend on how many earlier rows had succeeded, which
    # sent an earlier diagnosis chasing an entirely different parameter set.
    # Each job carries its own rng so prompts stay deterministic per index.
    plan = []
    for i in range(args.n):
        cls = classes[i % len(classes)]
        plan.append((i, cls, sample_params(cls, rng),
                     random.Random(args.seed * 1000 + i)))

    stats = {c: [0, 0] for c in classes}
    for _, cls, _, _ in plan:
        stats[cls][1] += 1

    def run_one(job: tuple) -> dict:
        i, cls, params, prng = job
        try:
            spec, resolved = make_spec(cls, params)
            if spec is None or resolved is None:
                return {"i": i, "cls": cls, "ok": False,
                        "why": "cannot assemble at these parameters"}
            t0 = time.time()
            v = build_assembly(resolved, workdir=workdir,
                               tag=f"{cls}_{i:04d}")
            el = round(time.time() - t0, 1)
        except Exception as e:                    # noqa: BLE001
            return {"i": i, "cls": cls, "ok": False, "params": params,
                    "why": f"{type(e).__name__}: {str(e)[:70]}"}
        if not v.get("passed"):
            why = (v.get("error") or
                   ",".join(str(a["id"]) for a in v.get("assertions", [])
                            if not a["passed"]) or
                   ",".join(str(p.get("id")) for p in
                            v.get("failed_preconditions", [])))
            return {"i": i, "cls": cls, "ok": False, "params": params,
                    "why": str(why)[:60]}

        motion = None
        if cls == "planetary_stage":
            from .ekg import planetary_motion_graph
            motion = planetary_motion_graph(
                int(spec["variables"]["z_sun"]),
                int(spec["variables"]["z_planet"]),
                int(spec["variables"]["n_planets"]))
        dims = [(k, val, k.replace("_", " "))
                for k, val in list(spec["variables"].items())[:6]
                if isinstance(val, (int, float))]
        row = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(
                    spec["assembly_class"], [], dims, prng)},
                {"role": "assistant", "content":
                    f"<think>\n{think_block(spec, v, motion)}\n</think>\n\n"
                    + json.dumps(authored_target(spec))},
            ],
            "meta": {"assembly_class": cls,
                     "n_components": len(spec["components"]),
                     "n_mates": len(spec["mates"]),
                     "n_assertions": len(spec["assertions"]),
                     "elapsed_s": el},
        }
        return {"i": i, "cls": cls, "ok": True, "row": row, "el": el,
                "nc": len(spec["components"]), "nm": len(spec["mates"])}

    t_all = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_one, plan))
    wall = time.time() - t_all

    rows = []
    for r in sorted(results, key=lambda x: x["i"]):
        if r["ok"]:
            stats[r["cls"]][0] += 1
            rows.append(r["row"])
            print(f"[{r['i']:4d}] {r['cls']:18s} OK   {r['el']:6.1f}s  "
                  f"{r['nc']} parts, {r['nm']} mates")
        else:
            print(f"[{r['i']:4d}] {r['cls']:18s} FAIL {r['why']}"
                  + (f" | {r.get('params')}" if r.get("params") else ""))
    print(f"\nwall {wall / 60:.1f} min with {args.workers} workers "
          f"({3600 * len(plan) / max(wall, 1):.0f} assemblies/hour)")

    path = os.path.join(args.out, "assemblies.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nverified {len(rows)}/{args.n}")
    for c, (ok, tot) in stats.items():
        print(f"  {c:20s} {ok}/{tot}")
    if rows:
        ln = sorted(sum(len(m["content"]) for m in r["messages"]) for r in rows)
        print(f"  target chars: median {ln[len(ln)//2]}  max {ln[-1]}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
