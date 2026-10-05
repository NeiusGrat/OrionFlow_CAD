"""Seeded-error accuracy run: recall per rule, false alarms on clean assemblies.

    python -m interface_check.bench [--out data/interface_check/bench]

A false alarm is a high or medium finding on a clean assembly. Low and info
findings (hardware absent from CAD, assumptions) are listed but not counted.
A seeded error is caught when its rule fires; for revision cases the diff must
also list the changed part and label the finding "new".
"""
from __future__ import annotations

import argparse
import json
import time
import warnings
from collections import defaultdict
from pathlib import Path

from .pipeline import run_check
from .synth import ASSEMBLIES, MUTATIONS, Mutation, build

ALARM = ("high", "medium")


def _run(paths: dict, prev: dict | None = None):
    return run_check(paths["step"], bom=paths.get("bom"), urdf=paths.get("urdf"), urdf_map=paths.get("urdf_map"),
                     prev_step=prev["step"] if prev else None, prev_bom=prev.get("bom") if prev else None)


def run(out: Path, mutations: list[Mutation] | None = None) -> dict:
    warnings.filterwarnings("ignore")
    mutations = MUTATIONS if mutations is None else mutations
    result = {"clean": {}, "seeded": [], "recall": {}, "false_alarms": {}}
    for name in ASSEMBLIES:
        paths = build(name, {}, out / "clean", name)
        t0 = time.time()
        r = _run(paths)
        alarms = [f for f in r.findings if f.severity in ALARM]
        result["clean"][name] = {"runtime_s": round(time.time() - t0, 2), "alarms": len(alarms),
                                 "findings": [f"{f.severity} {f.rule_id}: {f.message}" for f in r.findings],
                                 "llm_calls": r.llm_usage.get("calls", 0)}
        result["false_alarms"][name] = len(alarms)

    per_rule = defaultdict(lambda: [0, 0])
    for m in mutations:
        paths = build(m.assembly, m.params, out / "seeded", m.id)
        prev = build(m.assembly, m.prev, out / "seeded", m.id + "_prev") if m.prev is not None else None
        t0 = time.time()
        r = _run(paths, prev)
        hits = [f for f in r.findings if f.rule_id == m.expect] if m.expect else []
        alarms = [f for f in r.findings if f.severity in ALARM]
        if m.expect:
            caught = bool(hits)
            if m.prev is not None:
                changed = {c["part"] for c in r.changes}
                caught = caught and set(m.expect_change) <= changed and any(f.change_status == "new" for f in hits)
            per_rule[m.expect][1] += 1
            per_rule[m.expect][0] += int(caught)
        else:
            caught = not alarms                  # a "must stay clean" case
            per_rule["(no alarm)"][1] += 1
            per_rule["(no alarm)"][0] += int(caught)
        result["seeded"].append({
            "id": m.id, "expect": m.expect, "note": m.note, "caught": caught,
            "runtime_s": round(time.time() - t0, 2),
            "fired": sorted({f.rule_id for f in r.findings if f.severity != "info"}),
            "message": hits[0].message if hits else None,
            "changes": [f"{c['part']}: {c['status']} {c['details'][:2]} neighbours={c['neighbours']}"
                        for c in r.changes],
        })
    result["recall"] = {k: {"caught": v[0], "seeded": v[1], "recall": round(v[0] / v[1], 3)}
                        for k, v in sorted(per_rule.items())}
    seeded = [s for s in result["seeded"] if s["expect"]]
    result["total"] = {"seeded": len(seeded), "caught": sum(s["caught"] for s in seeded),
                       "recall": round(sum(s["caught"] for s in seeded) / max(len(seeded), 1), 3),
                       "max_false_alarms_per_assembly": max(result["false_alarms"].values(), default=0)}
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/interface_check/bench")
    args = ap.parse_args()
    out = Path(args.out)
    res = run(out)
    (out / "accuracy.json").write_text(json.dumps(res, indent=2))
    for rule, r in res["recall"].items():
        print(f"{rule:26s} {r['caught']}/{r['seeded']}  {r['recall']:.0%}")
    for s in res["seeded"]:
        if not s["caught"]:
            print(f"MISSED {s['id']}: expected {s['expect']}, fired {s['fired']}")
    print("false alarms per clean assembly:", res["false_alarms"])
    print("total:", res["total"])


if __name__ == "__main__":
    main()
