"""CLI: validate all pairs in a JSONL by execution."""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser(description="Validate OFL training pairs by execution")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--output", default=None, help="Output JSONL with only valid pairs")
    args = parser.parse_args()

    from orionflow_ofl.data_pipeline.validator import OFLValidator

    pairs = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                pairs.append(json.loads(line))

    print(f"Validating {len(pairs)} pairs with {args.workers} workers...")
    validator = OFLValidator()
    stats = validator.batch_validate(pairs, max_workers=args.workers)

    print(f"\nResults: {stats['valid']}/{stats['total']} valid ({100*stats['valid']/max(stats['total'],1):.1f}%)")
    if stats["error_summary"]:
        print("Error breakdown:")
        for err, cnt in sorted(stats["error_summary"].items(), key=lambda x: -x[1]):
            print(f"  {cnt}x {err}")

    if args.output:
        out_dir = os.path.dirname(args.output) or "."
        os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for p in stats["valid_pairs"]:
                # remove validation metadata
                clean = {k: v for k, v in p.items() if k in ("text", "code", "source", "complexity")}
                f.write(json.dumps(clean, ensure_ascii=False) + "\n")
        print(f"Valid pairs written to: {args.output}")

    # write report
    report_path = (args.output or args.input).replace(".jsonl", "_validation_report.json")
    report = {
        "total": stats["total"],
        "valid": stats["valid"],
        "invalid": stats["invalid"],
        "error_summary": stats["error_summary"],
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
