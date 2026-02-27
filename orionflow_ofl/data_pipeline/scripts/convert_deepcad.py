"""CLI: batch convert DeepCAD JSON -> OFL training pairs."""

import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Convert DeepCAD JSON to OFL training pairs"
    )

    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing DeepCAD JSON files",
    )

    parser.add_argument(
        "--output-dir",
        default="data/deepcad_ofl",
        help="Output directory",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Number of models to process (0 = all remaining)",
    )

    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Start index in sorted file list",
    )

    parser.add_argument(
        "--scale",
        type=float,
        default=50.0,
        help="Scale factor for DeepCAD coords",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (1 = sequential)",
    )

    args = parser.parse_args()

    from orionflow_ofl.data_pipeline.deepcad_converter import DeepCADConverter
    from orionflow_ofl.data_pipeline.dataset_builder import DatasetBuilder

    builder = DatasetBuilder(output_dir=args.output_dir)
    builder.converter = DeepCADConverter(scale=args.scale)

    path = builder.build_from_deepcad(
        deepcad_dir=args.input_dir,
        limit=args.limit,
        offset=args.offset,
        workers=args.workers,
    )

    print(f"Output: {path}")


if __name__ == "__main__":
    main()
