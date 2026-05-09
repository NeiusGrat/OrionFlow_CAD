"""Phase 2: Stream Zero-To-CAD-100k, filter top ~20% by complexity.

Filter band (balanced): 8 <= num_faces <= 60, 5 <= cadquery_ops_count <= 40.
Output:
  raw/<split>.jsonl          - one row per sample (uuid, code, ops_json, meta, image_path)
  images/<uuid>.png          - the first rendered view per kept sample
  logs/phase2_progress.json  - resumable progress per split

Resumable: re-running skips uuids already in raw/<split>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from datasets import load_dataset
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw"
IMG_DIR = ROOT / "images"
LOG_DIR = ROOT / "logs"

DATASET_ID = "ADSKAILab/Zero-To-CAD-100k"
SPLITS = ("train", "validation", "test")

# Balanced filter band
FACE_MIN, FACE_MAX = 8, 60
OPS_MIN, OPS_MAX = 5, 40


def passes_filter(num_faces: int, ops_count: int) -> bool:
    return FACE_MIN <= num_faces <= FACE_MAX and OPS_MIN <= ops_count <= OPS_MAX


def complexity_score(num_faces: int, ops_count: int) -> float:
    # Mid-band-favoring score: rewards moderate complexity, penalizes extremes
    face_norm = (num_faces - FACE_MIN) / (FACE_MAX - FACE_MIN)
    ops_norm = (ops_count - OPS_MIN) / (OPS_MAX - OPS_MIN)
    return round(0.6 * ops_norm + 0.4 * face_norm, 4)


def load_seen_uuids(jsonl_path: Path) -> set[str]:
    if not jsonl_path.exists():
        return set()
    seen = set()
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                seen.add(json.loads(line)["uuid"])
            except Exception:
                continue
    return seen


def stream_split(split: str, max_kept: int | None, log_every: int = 500) -> dict:
    out_path = RAW_DIR / f"{split}.jsonl"
    seen = load_seen_uuids(out_path)
    print(f"[{split}] resuming, {len(seen)} already kept", flush=True)

    ds = load_dataset(DATASET_ID, split=split, streaming=True)

    kept = len(seen)
    scanned = 0
    t0 = time.time()

    pbar = tqdm(total=max_kept, initial=kept, desc=f"{split}", unit="kept")
    with out_path.open("a", encoding="utf-8") as f:
        for row in ds:
            scanned += 1
            uuid = row["uuid"]
            if uuid in seen:
                continue

            num_faces = row["num_faces"]
            ops_count = row["cadquery_ops_count"]
            if not passes_filter(num_faces, ops_count):
                continue

            try:
                code = row["cadquery_file"].decode("utf-8", errors="replace")
            except Exception:
                continue

            img_path = IMG_DIR / f"{uuid}.png"
            try:
                with img_path.open("wb") as imgf:
                    imgf.write(row["image_0"])
            except Exception as e:
                print(f"[{split}] image write failed for {uuid}: {e}", flush=True)
                continue

            record = {
                "uuid": uuid,
                "split": split,
                "num_faces": num_faces,
                "ops_count": ops_count,
                "score": complexity_score(num_faces, ops_count),
                "image_path": str(img_path.relative_to(ROOT)).replace("\\", "/"),
                "code": code,
                "ops_json": row["cadquery_ops_json"],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            seen.add(uuid)
            kept += 1
            pbar.update(1)

            if scanned % log_every == 0:
                elapsed = time.time() - t0
                rate = scanned / elapsed if elapsed > 0 else 0.0
                tqdm.write(
                    f"[{split}] scanned={scanned} kept={kept} "
                    f"rate={rate:.1f}/s elapsed={elapsed:.0f}s"
                )

            if max_kept is not None and kept >= max_kept:
                tqdm.write(f"[{split}] reached cap of {max_kept}, stopping")
                break

    pbar.close()
    return {
        "split": split,
        "scanned": scanned,
        "kept": kept,
        "elapsed_s": round(time.time() - t0, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="all")
    parser.add_argument(
        "--cap-train", type=int, default=20000,
        help="Max samples to keep from train split"
    )
    parser.add_argument(
        "--cap-val", type=int, default=2500,
        help="Max samples to keep from validation split"
    )
    parser.add_argument(
        "--cap-test", type=int, default=2500,
        help="Max samples to keep from test split"
    )
    parser.add_argument(
        "--smoke", type=int, default=0,
        help="If >0, override caps with this small number for testing"
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        caps = {"train": args.smoke, "validation": args.smoke, "test": args.smoke}
    else:
        caps = {
            "train": args.cap_train,
            "validation": args.cap_val,
            "test": args.cap_test,
        }

    splits = SPLITS if args.split == "all" else (args.split,)
    summary = []
    for split in splits:
        result = stream_split(split, caps[split])
        summary.append(result)

    log_path = LOG_DIR / "phase2_progress.json"
    log_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("=" * 60)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
