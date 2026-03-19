"""Merge the existing OrionFlow training shards into the final dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from generate_final_dataset import (  # noqa: E402
    EDITING_PATH,
    EXAMPLES_PATH,
    SYNTHETIC_PATH,
    ensure_training_dir,
    merge_and_finalize,
)


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--spot-check-count", type=int, default=20)
    args = parser.parse_args()

    ensure_training_dir()

    synthetic_records = load_jsonl(SYNTHETIC_PATH)
    example_records = load_jsonl(EXAMPLES_PATH)
    editing_records = load_jsonl(EDITING_PATH)

    print("Merging existing dataset shards")
    print(f"  synthetic: {len(synthetic_records)}")
    print(f"  examples:  {len(example_records)}")
    print(f"  editing:   {len(editing_records)}")
    print(f"  combined:  {len(synthetic_records) + len(example_records) + len(editing_records)}")

    final_records = merge_and_finalize(
        synthetic_records=synthetic_records,
        example_records=example_records,
        editing_records=editing_records,
        spot_check_count=args.spot_check_count,
        seed=args.seed,
    )
    print(f"Final records written: {len(final_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
