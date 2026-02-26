"""CLI: generate N synthetic OFL training pairs."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic OFL training pairs")
    parser.add_argument("--num-samples", type=int, default=5000, help="Number of samples")
    parser.add_argument("--output", default="data/synthetic/synthetic_pairs.jsonl", help="Output JSONL")
    parser.add_argument("--validate", type=str, default="false", help="Validate generated pairs (true/false)")
    args = parser.parse_args()

    import os
    from orionflow_ofl.data_pipeline.dataset_builder import DatasetBuilder

    out_dir = os.path.dirname(args.output) or "."
    builder = DatasetBuilder(output_dir=out_dir)
    path = builder.build_synthetic(num_samples=args.num_samples)
    print(f"Output: {path}")

    if args.validate.lower() == "true":
        import json
        from orionflow_ofl.data_pipeline.validator import OFLValidator

        pairs = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    pairs.append(json.loads(line))
        validator = OFLValidator()
        stats = validator.batch_validate(pairs, max_workers=4)
        print(f"Validation: {stats['valid']}/{stats['total']} valid")
        if stats["error_summary"]:
            print("Errors:")
            for err, cnt in sorted(stats["error_summary"].items(), key=lambda x: -x[1]):
                print(f"  {cnt}x {err}")


if __name__ == "__main__":
    main()
