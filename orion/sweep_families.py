"""Build a stratified sample from every family in a packed set.

The eval harness scores a random slice, which is dominated by whatever families
are largest — a family that is 100% broken can hide inside a 97% headline. This
sweeps *per family* so a systematically bad family cannot be averaged away, and
it runs before training rather than after.

    python -m orion.sweep_families --data data/forge/sft_v1/train.jsonl \
        --per-family 3 --workers 6
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import tempfile
from concurrent.futures import ThreadPoolExecutor

from .eval_blueprint import score_one


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data/forge/sft_v1/train.jsonl")
    ap.add_argument("--per-family", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1602)
    ap.add_argument("--out", default=None, help="write per-sample json here")
    ap.add_argument("--keep", default=None,
                    help="keep FCStd files in this dir instead of a temp dir")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8")]
    by_family: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        by_family[r["meta"].get("base_family") or "?"].append(r)

    rng = random.Random(args.seed)
    picked = []
    for fam in sorted(by_family):
        pool = by_family[fam]
        for r in rng.sample(pool, min(args.per_family, len(pool))):
            picked.append(r)

    print(f"{len(by_family)} families | {len(rows)} rows | "
          f"building {len(picked)} parts with {args.workers} workers")

    workdir = args.keep or tempfile.mkdtemp(prefix="orion_sweep_")
    os.makedirs(workdir, exist_ok=True)

    def run(t):
        i, row = t
        return score_one(i, row["messages"][2]["content"], row["meta"], workdir)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, enumerate(picked)))

    per_fam: dict[str, list] = collections.defaultdict(list)
    for row, res in zip(picked, results):
        per_fam[row["meta"].get("base_family") or "?"].append(res)

    print("\n{:<34} {:>5} {:>7}  {}".format("family", "n", "passed", "failures"))
    print("-" * 78)
    broken, partial = [], []
    for fam in sorted(per_fam):
        res = per_fam[fam]
        ok = sum(r["verified"] for r in res)
        errs = sorted({(r["error"] or "").split(":")[0]
                       for r in res if not r["verified"]} - {""})
        flag = "" if ok == len(res) else "  <<<"
        print("{:<34} {:>5} {:>7}  {}{}".format(
            fam[:34], len(res), f"{ok}/{len(res)}", ",".join(errs), flag))
        if ok == 0:
            broken.append(fam)
        elif ok < len(res):
            partial.append(fam)

    n = len(results)
    ok = sum(r["verified"] for r in results)
    print("-" * 78)
    print(f"TOTAL {ok}/{n} verified ({100.0*ok/max(n,1):.1f}%)  "
          f"| fully broken families: {len(broken)}  partial: {len(partial)}")
    if broken:
        print("  BROKEN : " + ", ".join(broken))
    if partial:
        print("  PARTIAL: " + ", ".join(partial))

    fails = [(r, p) for r, p in zip(results, picked) if not r["verified"]]
    if fails:
        print("\nfirst failures in detail:")
        for r, p in fails[:12]:
            print(f"  [{p['meta'].get('base_family')}] "
                  f"{r.get('part_class', p['meta']['part_class'])[:44]}")
            print(f"      {r['error']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"total": n, "verified": ok,
                       "broken_families": broken, "partial_families": partial,
                       "results": results}, fh, indent=1)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
