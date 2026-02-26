"""Download (if needed) and batch convert DeepCAD JSON -> OFL training pairs.

DeepCAD dataset: https://github.com/ChrisWu1997/DeepCAD
Processed JSON files (~246MB) should be placed at: data/deepcad_raw/

Usage:
    python -m orionflow_ofl.data_pipeline.scripts.download_and_convert_deepcad \
        --input-dir data/deepcad_raw/ \
        --output data/training/deepcad_pairs.jsonl \
        --workers 8
"""

import argparse
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def _convert_single(args_tuple: tuple) -> dict | None:
    """Convert one DeepCAD JSON -> dict with code + descriptions, or None."""
    json_path, scale = args_tuple
    # import inside worker to avoid pickling issues
    from orionflow_ofl.data_pipeline.deepcad_converter import DeepCADConverter
    from orionflow_ofl.data_pipeline.text_annotator import TextAnnotator

    converter = DeepCADConverter(scale=scale)
    annotator = TextAnnotator()

    try:
        with open(json_path, encoding="utf-8") as f:
            deepcad = json.load(f)

        model_id = Path(json_path).stem
        code = converter.convert(deepcad, model_id=model_id)
        if code is None:
            return None

        descriptions = annotator.annotate_from_code(code)
        return {
            "code": code,
            "descriptions": descriptions,
            "model_id": model_id,
        }
    except Exception:
        return None


def _estimate_complexity(code: str) -> int:
    has_hole = "Hole(" in code
    hole_count = code.count("Hole(")
    has_pattern = "at_circular" in code
    if not has_hole:
        return 1
    if hole_count == 1 and not has_pattern:
        return 2
    if has_pattern:
        return 3
    if hole_count >= 3:
        return 4
    return 2


def main():
    parser = argparse.ArgumentParser(description="Convert DeepCAD JSON to OFL training pairs")
    parser.add_argument("--input-dir", required=True, help="Directory with DeepCAD JSON files")
    parser.add_argument("--output", default="data/training/deepcad_pairs.jsonl")
    parser.add_argument("--scale", type=float, default=50.0)
    parser.add_argument("--max-models", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--validate-sample", type=int, default=100)
    args = parser.parse_args()

    json_files = sorted(Path(args.input_dir).glob("**/*.json"))
    if not json_files:
        print(f"ERROR: No JSON files found in {args.input_dir}")
        print("Download DeepCAD processed data and place JSON files there.")
        print("See: https://github.com/ChrisWu1997/DeepCAD")
        sys.exit(1)

    if args.max_models:
        json_files = json_files[: args.max_models]

    print(f"Found {len(json_files)} DeepCAD models")
    print(f"Converting with scale={args.scale}x ...")

    converted: list[dict] = []
    failed = 0
    tasks = [(str(f), args.scale) for f in json_files]

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_convert_single, t): t for t in tasks}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result:
                converted.append(result)
            else:
                failed += 1
            if (i + 1) % 1000 == 0:
                rate = len(converted) / (i + 1) * 100
                print(f"  {i + 1}/{len(tasks)}: {len(converted)} converted ({rate:.0f}%)")

    total = len(converted) + failed
    print(
        f"\nConversion: {len(converted)} success, {failed} failed "
        f"({len(converted) / max(total, 1) * 100:.0f}% rate)"
    )

    # build training pairs
    pairs: list[dict] = []
    for item in converted:
        for desc in item["descriptions"]:
            pairs.append({
                "text": desc,
                "code": item["code"],
                "source": "deepcad",
                "complexity": _estimate_complexity(item["code"]),
            })

    # save
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    print(f"Saved {len(pairs)} training pairs to {args.output}")

    # validate sample
    if args.validate_sample and converted:
        from orionflow_ofl.data_pipeline.validator import OFLValidator

        print(f"\nValidating {args.validate_sample} samples...")
        validator = OFLValidator()
        random.seed(42)
        sample = random.sample(converted, min(args.validate_sample, len(converted)))
        valid = sum(1 for item in sample if validator.validate(item["code"])["valid"])
        print(f"Validation: {valid}/{len(sample)} produce valid STEP ({valid / len(sample) * 100:.0f}%)")

    # summary
    print(f"\n{'=' * 50}")
    print("DeepCAD Conversion Summary")
    print(f"{'=' * 50}")
    print(f"Total models:     {len(json_files)}")
    print(f"Converted:        {len(converted)}")
    print(f"Training pairs:   {len(pairs)}")
    print(f"Conversion rate:  {len(converted) / max(len(json_files), 1) * 100:.0f}%")

    # save report
    report_path = args.output.replace(".jsonl", "_report.json")
    Path(report_path).write_text(
        json.dumps({
            "total_models": len(json_files),
            "converted": len(converted),
            "failed": failed,
            "training_pairs": len(pairs),
            "conversion_rate_pct": round(len(converted) / max(total, 1) * 100, 1),
        }, indent=2)
    )


if __name__ == "__main__":
    main()
