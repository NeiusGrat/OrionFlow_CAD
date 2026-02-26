"""CLI: assemble final training_pairs.jsonl from multiple sources."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Build merged training dataset")
    parser.add_argument("--sources", nargs="+", required=True, help="Input JSONL files")
    parser.add_argument("--output", default="data/training/training_pairs.jsonl", help="Output JSONL")
    parser.add_argument("--shuffle", type=str, default="true", help="Shuffle output (true/false)")
    args = parser.parse_args()

    import os
    from orionflow_ofl.data_pipeline.dataset_builder import DatasetBuilder

    out_dir = os.path.dirname(args.output) or "."
    builder = DatasetBuilder(output_dir=out_dir)
    stats = builder.merge_and_deduplicate(args.sources, args.output)
    print(f"Output: {args.output}")
    print(f"Stats: {stats}")


if __name__ == "__main__":
    main()
