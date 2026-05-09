"""Phase 7b: Remove uuid duplicates between val/test splits.

Source dataset has 107 uuids in BOTH validation and test. Drop them from
validation (keep test pristine). Run AFTER phase7_pack_jsonl.py.

Modifies dataset/<split>.jsonl in place by writing a deduplicated copy.
Original raw/, analyzed/, prompts/ files are untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "dataset"


def load_uuids(path: Path) -> set[str]:
    s: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            s.add(json.loads(line)["meta"]["uuid"])
    return s


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    train_uuids = load_uuids(DATASET_DIR / "train.jsonl")
    val_uuids = load_uuids(DATASET_DIR / "validation.jsonl")
    test_uuids = load_uuids(DATASET_DIR / "test.jsonl")

    overlap_val_test = val_uuids & test_uuids
    overlap_train_val = train_uuids & val_uuids
    overlap_train_test = train_uuids & test_uuids
    drop_from_val = overlap_val_test | overlap_train_val
    drop_from_test = overlap_train_test

    print(f"Before dedupe: train={len(train_uuids)} val={len(val_uuids)} test={len(test_uuids)}")
    print(f"  overlap val/test = {len(overlap_val_test)}")
    print(f"  overlap train/val = {len(overlap_train_val)}")
    print(f"  overlap train/test = {len(overlap_train_test)}")
    print(f"  drop from val: {len(drop_from_val)}")
    print(f"  drop from test: {len(drop_from_test)}")

    def filter_split(name: str, drop: set[str]) -> int:
        in_path = DATASET_DIR / f"{name}.jsonl"
        out_path = DATASET_DIR / f"{name}.jsonl.tmp"
        kept = 0
        with in_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
            for line in fin:
                row = json.loads(line)
                if row["meta"]["uuid"] in drop:
                    continue
                fout.write(line)
                kept += 1
        in_path.unlink()
        out_path.rename(in_path)
        return kept

    final_val = filter_split("validation", drop_from_val) if drop_from_val else len(val_uuids)
    final_test = filter_split("test", drop_from_test) if drop_from_test else len(test_uuids)
    final_train = len(train_uuids)

    summary = {"train": final_train, "validation": final_val, "test": final_test, "total": final_train + final_val + final_test}
    print(f"After dedupe: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
