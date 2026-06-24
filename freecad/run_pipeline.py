"""End-to-end entry point.

    python -m freecad.run_pipeline --limit 100
    python -m freecad.run_pipeline --limit 100 --with-glb
    python -m freecad.run_pipeline --limit 100 --skip-download   # reuse local files
"""

from __future__ import annotations

import argparse
import json

from . import dataset_converter


def main() -> None:
    ap = argparse.ArgumentParser(description="gNucleus FCStd -> FeatureGraph pipeline")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--with-glb", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--skip-extract", action="store_true",
                    help="reuse raw_extract/ (remap only, no FreeCAD)")
    args = ap.parse_args()

    summary = dataset_converter.run(
        limit=args.limit, with_glb=args.with_glb,
        skip_download=args.skip_download, skip_extract=args.skip_extract,
    )
    printable = {k: v for k, v in summary.items() if k not in ("errors", "low_coverage")}
    print("\n===== PIPELINE SUMMARY =====")
    print(json.dumps(printable, indent=2))
    if summary.get("errors"):
        print(f"\n{len(summary['errors'])} error rows (see training/summary.json)")
    if summary.get("low_coverage"):
        print(f"{len(summary['low_coverage'])} rows < 100% param coverage")


if __name__ == "__main__":
    main()
