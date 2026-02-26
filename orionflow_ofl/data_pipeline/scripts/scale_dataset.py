"""Master script: generate 10K pairs, validate sample, filter, balance, save.

Usage:
    python -m orionflow_ofl.data_pipeline.scripts.scale_dataset \
        --num-pairs 10000 \
        --output data/training/synthetic_10k.jsonl \
        --validate-rate 0.1 \
        --workers 4
"""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser(
        description="Generate large-scale synthetic OFL training dataset"
    )
    parser.add_argument("--num-pairs", type=int, default=10000)
    parser.add_argument("--output", default="data/training/synthetic_10k.jsonl")
    parser.add_argument("--validate-rate", type=float, default=0.1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--merge-examples", action="store_true",
                        help="Also merge with example pairs into training_pairs_v2.jsonl")
    args = parser.parse_args()

    from orionflow_ofl.data_pipeline.scale_synthetic import ScaleSyntheticGenerator

    print(f"Generating {args.num_pairs} synthetic training pairs...")
    gen = ScaleSyntheticGenerator(seed=args.seed)
    stats = gen.generate_batch(
        num_pairs=args.num_pairs,
        validate=True,
        validate_sample_rate=args.validate_rate,
        output_path=args.output,
        workers=args.workers,
    )

    print(f"\n{'=' * 60}")
    print(f"SYNTHETIC GENERATION REPORT")
    print(f"{'=' * 60}")
    print(f"Raw generated:      {stats['raw_generated']}")
    print(f"After filter:       {stats['after_filter']}")
    print(f"After balance:      {stats['after_balance']}")
    print(f"Final count:        {stats['final_count']}")
    if stats.get("validation"):
        v = stats["validation"]
        print(f"Validation sample:  {v['valid']}/{v['sample_size']} ({v['valid_pct']}%)")
    print(f"Output:             {stats['output_path']}")
    print(f"\nComplexity distribution:")
    for c, n in sorted(stats.get("complexity_distribution", {}).items()):
        pct = n / stats["final_count"] * 100
        print(f"  Complexity {c}: {n:>5} ({pct:.1f}%)")
    print(f"\nTemplate distribution:")
    for t, n in sorted(stats.get("template_distribution", {}).items(), key=lambda x: -x[1]):
        print(f"  {t:<30} {n:>5}")

    # optionally merge with examples
    if args.merge_examples:
        from orionflow_ofl.data_pipeline.dataset_builder import DatasetBuilder

        out_dir = os.path.dirname(args.output) or "."
        builder = DatasetBuilder(output_dir=out_dir)

        # build example pairs if not already there
        ex_path = os.path.join(out_dir, "example_pairs.jsonl")
        if not os.path.exists(ex_path):
            ex_path = builder.build_from_examples()

        merged_path = os.path.join(out_dir, "training_pairs_v2.jsonl")
        merge_stats = builder.merge_and_deduplicate(
            [ex_path, args.output], merged_path
        )
        print(f"\nMerged dataset: {merge_stats['total_pairs']} pairs -> {merged_path}")
        print(f"Source breakdown: {merge_stats['source_breakdown']}")


if __name__ == "__main__":
    main()
