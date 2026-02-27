"""Download (if needed) and batch convert DeepCAD JSON -> OFL training pairs.

DeepCAD dataset: https://github.com/ChrisWu1997/DeepCAD
Processed JSON files (~246MB) should be placed at: data/deepcad_raw/

Usage:
    python -m orionflow_ofl.data_pipeline.scripts.download_and_convert_deepcad \
        --input-dir data/deepcad_raw/ \
        --output data/training/deepcad_pairs.jsonl \
        --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def _convert_single(args_tuple: tuple[str, float]) -> dict | None:
    """Convert one DeepCAD JSON -> dict with code + descriptions, or None."""
    json_path, scale = args_tuple
    # Import inside worker to avoid pickling issues.
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


def _reservoir_add(sample: list[dict], item: dict, seen: int, limit: int) -> None:
    """Keep a uniform random sample of at most ``limit`` items from a stream."""
    if limit <= 0:
        return
    if len(sample) < limit:
        sample.append(item)
        return
    replace_idx = random.randint(0, seen - 1)
    if replace_idx < limit:
        sample[replace_idx] = item


def _iter_conversion_results(tasks: list[tuple[str, float]], workers: int):
    """Yield conversion results using process pool when available, else sequential."""
    if workers <= 1:
        for task in tasks:
            yield _convert_single(task)
        return

    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_convert_single, t): t for t in tasks}
            for future in as_completed(futures):
                try:
                    yield future.result()
                except Exception:
                    yield None
    except (PermissionError, OSError) as exc:
        print(f"Process pool unavailable ({exc}); falling back to sequential conversion")
        for task in tasks:
            yield _convert_single(task)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert DeepCAD JSON to OFL training pairs")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", default="data/training/deepcad_pairs.jsonl")
    parser.add_argument("--scale", type=float, default=50.0)
    parser.add_argument("--max-models", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--validate-sample", type=int, default=0)
    args = parser.parse_args()

    json_files = sorted(Path(args.input_dir).glob("**/*.json"))
    if not json_files:
        print(f"No JSON files found in {args.input_dir}")
        sys.exit(1)

    if args.offset > 0:
        json_files = json_files[args.offset :]

    if args.max_models and args.max_models > 0:
        json_files = json_files[: args.max_models]

    if not json_files:
        print("No JSON files selected after applying offset/max-models")
        sys.exit(1)

    print(f"Processing {len(json_files)} models (offset={args.offset})")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    total = 0
    success = 0
    failed = 0
    pair_count = 0

    validate_cap = max(0, args.validate_sample)
    validation_sample: list[dict] = []

    with open(args.output, "w", encoding="utf-8") as outfile:
        tasks = [(str(f), args.scale) for f in json_files]

        for result in _iter_conversion_results(tasks, args.workers):
            total += 1

            if result is None:
                failed += 1
            else:
                success += 1
                code = result["code"]
                complexity = _estimate_complexity(code)

                for desc in result["descriptions"]:
                    pair = {
                        "text": desc,
                        "code": code,
                        "source": "deepcad",
                        "complexity": complexity,
                    }
                    outfile.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    pair_count += 1

                _reservoir_add(
                    validation_sample,
                    {"code": code, "model_id": result["model_id"]},
                    success,
                    validate_cap,
                )

            if total % 1000 == 0:
                rate = success / total * 100
                print(f"{total}: {success} converted ({rate:.1f}%)")

    print("\nConversion complete.")
    print(f"Success: {success}")
    print(f"Failed: {failed}")
    print(f"Rate: {success / max(total, 1) * 100:.1f}%")

    validation_report = None
    if validate_cap and validation_sample:
        from orionflow_ofl.data_pipeline.validator import OFLValidator

        print(f"\nValidating {len(validation_sample)} samples...")
        validator = OFLValidator()
        results = validator.batch_validate(validation_sample, max_workers=args.workers)

        valid = results["valid"]
        sample_size = len(validation_sample)
        print(f"Validation: {valid}/{sample_size} produce valid STEP ({valid / sample_size * 100:.0f}%)")

        validation_report = {
            "sample_size": sample_size,
            "valid": valid,
            "invalid": results["invalid"],
            "error_summary": results["error_summary"],
        }

    print(f"\n{'=' * 50}")
    print("DeepCAD Conversion Summary")
    print(f"{'=' * 50}")
    print(f"Total models:     {len(json_files)}")
    print(f"Converted:        {success}")
    print(f"Training pairs:   {pair_count}")
    print(f"Conversion rate:  {success / max(len(json_files), 1) * 100:.0f}%")

    output_path = Path(args.output)
    report_path = output_path.with_name(f"{output_path.stem}_report.json")
    report = {
        "total_models": len(json_files),
        "converted": success,
        "failed": failed,
        "training_pairs": pair_count,
        "conversion_rate_pct": round(success / max(total, 1) * 100, 1),
    }
    if validation_report is not None:
        report["validation"] = validation_report

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Saved {pair_count} training pairs to {args.output}")
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
