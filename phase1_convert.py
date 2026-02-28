"""
Phase 1 — DeepCAD JSON → OFL code string conversion.
Pure Python. Zero CAD dependencies. Safe on 8GB RAM.

Input  : data/deepcad_raw/**/*.json
Output : data/training/ofl_candidates.jsonl

Each output line is a JSON object:
  {
    "model_id":  "0001/00010001",    ← subdir/stem, unique key
    "code":      "from orionflow_ofl import *\n...",
    "source":    "deepcad"
  }
"""

from __future__ import annotations

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).resolve().parent
INPUT_DIR      = PROJECT_ROOT / "data" / "deepcad_raw"
OUTPUT_DIR     = PROJECT_ROOT / "data" / "training"
OUTPUT_FILE    = OUTPUT_DIR / "ofl_candidates.jsonl"
PROGRESS_FILE  = OUTPUT_DIR / "ofl_candidates_progress.json"
LOG_FILE       = OUTPUT_DIR / "phase1_convert.log"

# ── Settings ─────────────────────────────────────────────────
SCALE          = 50.0   # DeepCAD unit → mm
N_WORKERS      = 4      # threads (pure Python, GIL is fine here)
CHECKPOINT_N   = 1000   # write progress report every N files
LOG_LEVEL      = logging.INFO

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
    ],
)
log = logging.getLogger("phase1")


def _make_model_id(json_path: Path, input_dir: Path) -> str:
    """Stable unique ID: relative path without extension.
    e.g.  data/deepcad_raw/cad_json/0001/00010001.json  →  'cad_json/0001/00010001'
    """
    return str(json_path.relative_to(input_dir).with_suffix("")).replace("\\", "/")


def _convert_one(json_path: Path, input_dir: Path, scale: float) -> dict | None:
    """Convert a single JSON file. Returns dict or None on failure."""
    from orionflow_ofl.data_pipeline.deepcad_converter import DeepCADConverter
    from orionflow_ofl.data_pipeline.deepcad_preprocessor import preprocess_deepcad

    model_id = _make_model_id(json_path, input_dir)
    try:
        raw = json_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("read fail %s: %s", model_id, exc)
        return None

    # If data is in raw Fusion 360 format (has 'entities' key), preprocess first.
    # Raw format: sequence items have {"type": "Sketch", "entity": "id"}
    # Simplified format: sequence items have {"type": "sketch", "plane": {...}, "loops": [...]}
    if "entities" in data:
        try:
            data = preprocess_deepcad(data)
        except Exception as exc:
            log.debug("preprocess fail %s: %s", model_id, exc)
            return None
        if data is None:
            return None

    try:
        converter = DeepCADConverter(scale=scale)
        code = converter.convert(data, model_id=model_id)
    except Exception as exc:
        log.debug("convert exception %s: %s", model_id, exc)
        return None

    if code is None:
        return None

    return {
        "model_id": model_id,
        "code":     code,
        "source":   "deepcad",
    }


def main() -> None:
    t_start = time.perf_counter()

    # ── Sanity checks ─────────────────────────────────────────
    if not INPUT_DIR.exists():
        log.error("INPUT_DIR not found: %s", INPUT_DIR)
        log.error("Please ensure DeepCAD JSON files are in data/deepcad_raw/")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Discover all JSON files ───────────────────────────────
    log.info("Scanning %s ...", INPUT_DIR)
    all_paths = sorted(INPUT_DIR.rglob("*.json"))
    total_files = len(all_paths)

    if total_files == 0:
        log.error("No JSON files found in %s", INPUT_DIR)
        sys.exit(1)

    log.info("Found %d JSON files", total_files)

    # ── Resume support: skip already-converted model_ids ─────
    already_done: set[str] = set()
    if OUTPUT_FILE.exists():
        log.info("Found existing %s — resuming, skipping duplicates", OUTPUT_FILE.name)
        with OUTPUT_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    already_done.add(json.loads(line)["model_id"])
                except Exception:
                    pass
        log.info("  %d already converted, will skip these", len(already_done))

    remaining_paths = [
        p for p in all_paths
        if _make_model_id(p, INPUT_DIR) not in already_done
    ]
    log.info("%d files to process this run", len(remaining_paths))

    # ── Convert ───────────────────────────────────────────────
    converted   = len(already_done)   # total including previous runs
    failed      = 0
    processed   = 0

    fout = OUTPUT_FILE.open("a", encoding="utf-8")   # append mode for resume

    def _handle(json_path: Path) -> dict | None:
        return _convert_one(json_path, INPUT_DIR, SCALE)

    try:
        with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
            futures = {pool.submit(_handle, p): p for p in remaining_paths}

            for future in as_completed(futures):
                processed += 1
                result = future.result()

                if result is not None:
                    fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                    converted += 1
                else:
                    failed += 1

                # ── Progress log ──────────────────────────────
                if processed % CHECKPOINT_N == 0 or processed == len(remaining_paths):
                    elapsed  = time.perf_counter() - t_start
                    rate     = processed / elapsed if elapsed > 0 else 0
                    pct      = processed / len(remaining_paths) * 100 if remaining_paths else 100
                    eta_s    = (len(remaining_paths) - processed) / rate if rate > 0 else 0

                    log.info(
                        "[%5.1f%%] processed=%d  converted=%d  failed=%d  "
                        "rate=%.0f/s  ETA=%.0fs",
                        pct, processed, converted, failed, rate, eta_s,
                    )

                    # Write checkpoint JSON
                    PROGRESS_FILE.write_text(json.dumps({
                        "processed":        processed,
                        "total_remaining":  len(remaining_paths),
                        "converted_total":  converted,
                        "failed_this_run":  failed,
                        "elapsed_s":        round(elapsed, 1),
                        "rate_per_s":       round(rate, 1),
                    }, indent=2))

    finally:
        fout.close()

    # ── Final report ──────────────────────────────────────────
    elapsed = time.perf_counter() - t_start
    conversion_rate = converted / total_files * 100 if total_files else 0

    log.info("=" * 60)
    log.info("PHASE 1 COMPLETE")
    log.info("  Total JSON files   : %d", total_files)
    log.info("  Converted (total)  : %d  (%.1f%%)", converted, conversion_rate)
    log.info("  Failed this run    : %d", failed)
    log.info("  Wall time          : %.1f s", elapsed)
    log.info("  Output file        : %s", OUTPUT_FILE)
    log.info("  Output size        : %.1f MB", OUTPUT_FILE.stat().st_size / 1e6)
    log.info("=" * 60)

    # Final progress checkpoint
    PROGRESS_FILE.write_text(json.dumps({
        "status":           "complete",
        "total_json_files": total_files,
        "converted_total":  converted,
        "conversion_rate":  round(conversion_rate, 2),
        "failed_this_run":  failed,
        "elapsed_s":        round(elapsed, 1),
        "output_file":      str(OUTPUT_FILE),
        "output_size_mb":   round(OUTPUT_FILE.stat().st_size / 1e6, 2),
    }, indent=2))


if __name__ == "__main__":
    main()
