"""Sanity check: verify no UUID overlap across train/val/test."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\OrionFLow_CAD\CAD_DATA\zero_to_cad")
splits = {}
for split in ("train", "validation", "test"):
    p = ROOT / "dataset" / f"{split}.jsonl"
    uuids = set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            uuids.add(json.loads(line)["meta"]["uuid"])
    splits[split] = uuids
    print(f"{split:11s}: {len(uuids):6d} unique uuids")

print()
print("Cross-split overlaps:")
print(f"  train ^ val   : {len(splits['train'] & splits['validation'])}")
print(f"  train ^ test  : {len(splits['train'] & splits['test'])}")
print(f"  val   ^ test  : {len(splits['validation'] & splits['test'])}")
print(f"  total unique  : {len(splits['train'] | splits['validation'] | splits['test'])}")
