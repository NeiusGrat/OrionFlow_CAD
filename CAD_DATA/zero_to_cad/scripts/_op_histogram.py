"""Show the op-frequency histogram across the 24,893 filtered samples."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad\analyzed")
total = 0
sample_with_op: Counter = Counter()  # how many samples USE each op (any count)
total_op_count: Counter = Counter()  # total occurrences across all samples
base_solid_hist: Counter = Counter()
custom_profile_hist: Counter = Counter()  # samples with N custom profiles

for split in ("train", "validation", "test"):
    p = ROOT / f"{split}.jsonl"
    if not p.exists():
        continue
    with p.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            total += 1
            f_ = row["features"]
            base_solid_hist[f_["base_solid"]] += 1
            for op, n in f_["op_counts"].items():
                sample_with_op[op] += 1
                total_op_count[op] += n
            custom_profile_hist[f_["custom_profiles"]] += 1

print(f"Total samples analyzed: {total}\n")
print("Top 25 ops by sample-coverage (% of samples that use this op):")
for op, n in sample_with_op.most_common(25):
    print(f"  {op:25s} samples={n:6d}  ({100*n/total:5.1f}%)  total_uses={total_op_count[op]}")

print(f"\nBase solid distribution:")
for solid, n in base_solid_hist.most_common():
    print(f"  {solid:15s} {n:6d}  ({100*n/total:5.1f}%)")

print(f"\nCustom profile (moveTo/lineTo/threePointArc/spline/close) usage:")
for n, count in sorted(custom_profile_hist.items()):
    print(f"  {n} profiles: {count:6d} samples ({100*count/total:5.1f}%)")
