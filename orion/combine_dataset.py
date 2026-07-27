"""Combine V2 (parts) and V3 (gears, assemblies) into one training corpus.

The combining rule is a diversity cap, not a concatenation. v1 taught this the
expensive way: 25,560 samples of one prompt skeleton scored 95.3% on held-out
topologies and 50% on free engineering prose. Volume of a thing already
well-covered buys nothing; the marginal sample of a *new* concept buys a lot.

So every group — part family, gear, assembly class — is capped, and the cap is
reported next to what was actually available. A group at its cap is a signal
that more of it exists and was deliberately left out.

    python -m orion.combine_dataset --out data/forge/combined_v23
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def group_of(row: dict) -> tuple[str, str]:
    """(source, group) — the unit the diversity cap applies to."""
    m = row.get("meta", {})
    if "assembly_class" in m:
        return "assembly", m["assembly_class"]
    fam = m.get("base_family") or m.get("part_class") or "?"
    if m.get("part_class") == "spur_gear" or fam == "spur_gear":
        return "gear", "spur_gear"
    return "part", fam


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/forge/combined_v23")
    ap.add_argument("--part-cap", type=int, default=400,
                    help="max rows per single-part family")
    ap.add_argument("--assembly-cap", type=int, default=2000,
                    help="max rows per assembly class")
    ap.add_argument("--gear-cap", type=int, default=1500)
    ap.add_argument("--val-frac", type=float, default=0.04)
    ap.add_argument("--seed", type=int, default=1602)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(os.path.join(ROOT, args.out), exist_ok=True)

    # Sources are globbed rather than listed, so a new family's output is
    # picked up by existing in the right place instead of by remembering to
    # add it here. Assemblies accumulate across several runs and directories.
    import glob
    pool: list[dict] = []
    pool += _read(os.path.join(ROOT, "data/forge/sft_v2/train.jsonl"))
    pool += _read(os.path.join(ROOT, "data/forge/gears/gear_rows.jsonl"))
    for p in sorted(glob.glob(os.path.join(ROOT, "data/forge/asm_*",
                                           "assemblies.jsonl"))):
        pool += _read(p)

    # Several generation runs overlap in parameter space, so identical rows
    # appear more than once. Duplicates inflate a group's apparent coverage
    # without adding a single new concept, which is exactly what the cap is
    # meant to prevent.
    buckets: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    seen: set[str] = set()
    dupes = 0
    for r in pool:
        if "messages" not in r:
            continue
        key = r["messages"][2]["content"]
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        buckets[group_of(r)].append(r)
    if dupes:
        print(f"dropped {dupes:,} duplicate rows across overlapping runs\n")

    caps = {"part": args.part_cap, "assembly": args.assembly_cap,
            "gear": args.gear_cap}
    kept, report = [], []
    for (src, grp), rows in sorted(buckets.items()):
        rng.shuffle(rows)
        cap = caps[src]
        take = rows[:cap]
        kept += take
        report.append((src, grp, len(rows), len(take)))

    rng.shuffle(kept)
    n_val = max(1, int(len(kept) * args.val_frac))
    val, train = kept[:n_val], kept[n_val:]

    for name, rows in (("train", train), ("val", val)):
        p = os.path.join(ROOT, args.out, f"{name}.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{'source':10s} {'group':28s} {'avail':>7s} {'kept':>6s}")
    print("-" * 56)
    at_cap = 0
    for src, grp, avail, took in sorted(report, key=lambda x: (-x[3], x[1])):
        flag = ""
        if took == caps[src] and avail > took:
            flag = "  <- at cap"
            at_cap += 1
        print(f"{src:10s} {grp[:28]:28s} {avail:7,} {took:6,}{flag}")
    print("-" * 56)
    by_src = collections.Counter(s for s, _, _, _ in report)
    tot = collections.Counter()
    for s, _, _, t in report:
        tot[s] += t
    print(f"train {len(train):,}  val {len(val):,}  total {len(kept):,}")
    print("  " + "  ".join(f"{k}={tot[k]:,} ({by_src[k]} groups)"
                           for k in sorted(tot)))
    if at_cap:
        print(f"  {at_cap} group(s) truncated by the diversity cap — more of "
              "that concept exists and was deliberately left out")
    concepts = set()
    try:
        from .manifest import FAMILIES
        for _, grp, _, took in report:
            if took and grp in FAMILIES:
                concepts |= set(FAMILIES[grp]["concepts"])
        print(f"  engineering concepts represented: {len(concepts)}")
    except Exception:                              # noqa: BLE001
        pass
    print(f"\nwrote {os.path.join(args.out, 'train.jsonl')} "
          f"and val.jsonl")


if __name__ == "__main__":
    main()
