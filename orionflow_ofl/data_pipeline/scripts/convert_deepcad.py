"""CLI: batch convert DeepCAD JSON -> OFL training pairs."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Convert DeepCAD JSON to OFL training pairs")
    parser.add_argument("--input-dir", required=True, help="Directory containing DeepCAD JSON files")
    parser.add_argument("--output-dir", default="data/deepcad_ofl", help="Output directory")
    parser.add_argument("--max-models", type=int, default=0, help="Max models to convert (0=all)")
    parser.add_argument("--scale", type=float, default=50.0, help="Scale factor for DeepCAD coords")
    args = parser.parse_args()

    from orionflow_ofl.data_pipeline.deepcad_converter import DeepCADConverter
    from orionflow_ofl.data_pipeline.dataset_builder import DatasetBuilder

    builder = DatasetBuilder(output_dir=args.output_dir)
    builder.converter = DeepCADConverter(scale=args.scale)
    path = builder.build_from_deepcad(args.input_dir, max_models=args.max_models)
    print(f"Output: {path}")


if __name__ == "__main__":
    main()
