"""Resume final dataset generation from existing synthetic records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from generate_final_dataset import (
    SYNTHETIC_PATH,
    TextAnnotator,
    ensure_training_dir,
    generate_editing_records,
    generate_example_records,
    merge_and_finalize,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--editing-limit", type=int, default=3000)
    parser.add_argument("--spot-check-count", type=int, default=20)
    args = parser.parse_args()

    ensure_training_dir()
    annotator = TextAnnotator()

    with SYNTHETIC_PATH.open("r", encoding="utf-8") as handle:
        synthetic_records = [json.loads(line) for line in handle if line.strip()]
    print(f"Loaded synthetic records: {len(synthetic_records)}")

    example_records = generate_example_records(annotator)
    editing_records, summary = generate_editing_records(synthetic_records, args)
    print(f"Editing summary dict: {summary}")

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
