"""Phase 6 - assemble the final build123d-FTC training dataset.

Merges all phase outputs, deduplicates, quality-checks, shuffles, and
writes 90/5/5 train/val/test splits.

Inputs (defaults):
    data/build123d_ftc/templates_valid.jsonl    (Phase 1)
    data/build123d_ftc/deepcad_valid.jsonl      (Phase 2)
    data/build123d_ftc/editing_valid.jsonl      (Phase 3)
    data/build123d_ftc/complex_valid.jsonl      (Phase 4)
    data/build123d_ftc/rejection_raw.jsonl      (Phase 5, bypasses validator)

Output:
    data/build123d_ftc/final/train.jsonl
    data/build123d_ftc/final/val.jsonl
    data/build123d_ftc/final/test.jsonl
    data/build123d_ftc/final/manifest.json

Usage:
    python scripts/assemble_final_dataset.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Sample helpers
# ---------------------------------------------------------------------------

def _get_role(sample: dict, role: str) -> str:
    for m in sample.get("messages", []):
        if m.get("role") == role:
            return m.get("content", "")
    return ""


REFUSAL_CATS = {"impossible", "ambiguous", "out_of_scope", "partial"}


def _classify_source(sample: dict, src_hint: str) -> str:
    """Give every sample a canonical `source_bucket` field."""
    src = sample.get("source", "") or ""
    cat = sample.get("category", "") or ""
    if cat in REFUSAL_CATS:
        return f"rejection_{cat}"
    if "complex" in src_hint or "complex" in src:
        return "complex"
    if "edit" in src or "edit" in src_hint:
        if "deepcad" in src:
            return "edit_deepcad"
        return "edit_template"
    if "deepcad" in src or "deepcad" in src_hint:
        return "deepcad"
    if "template" in src_hint:
        return "template"
    return "other"


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------

EXPORT_CALL = re.compile(r"export_step\s*\(|export_stl\s*\(|\bexport\s*\(")
PARAMS_HDR = "# --- Parameters ---"
FEATURE_HDR = "# --- Feature Tree ---"
BUILDPART = "with BuildPart() as part:"
IMPORT_LINE = "from build123d import *"


def _is_refusal(sample: dict) -> bool:
    cat = sample.get("category", "") or ""
    return cat in {"impossible", "ambiguous", "out_of_scope"}


def _is_partial_refusal(sample: dict) -> bool:
    return (sample.get("category") or "") == "partial"


def _code_quality_ok(code: str) -> bool:
    """Basic structural checks for FTC code. Returns False on obvious junk."""
    if not code or len(code) < 100:
        return False
    if IMPORT_LINE not in code:
        return False
    if PARAMS_HDR not in code or FEATURE_HDR not in code:
        return False
    if BUILDPART not in code:
        return False
    if not EXPORT_CALL.search(code):
        return False
    # line-count sanity (FTC should be >= 10 lines)
    if code.count("\n") < 10:
        return False
    return True


def _partial_code_ok(assistant: str) -> bool:
    """Phase 5 partial samples embed code in a fenced block. Extract and check."""
    m = re.search(r"```python\n(.*?)\n```", assistant, re.DOTALL)
    if not m:
        return False
    return _code_quality_ok(m.group(1))


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def _normalize_code(code: str) -> str:
    """Normalize code for dedup: strip trailing whitespace per line."""
    return "\n".join(line.rstrip() for line in code.strip().splitlines())


def _dedup_key(sample: dict) -> str:
    """Stable hash for dedup.

    For CAD samples: MD5 of (normalized assistant code).
    For refusal samples: MD5 of (prompt + assistant).
    """
    prompt = _get_role(sample, "user")
    assistant = _get_role(sample, "assistant")
    if _is_refusal(sample):
        key = f"{prompt}\n---\n{assistant}"
    else:
        # For edit samples, also fold in the user prompt since the same
        # modified code could be produced from different source parts.
        key = f"{prompt[:500]}\n---\n{_normalize_code(assistant)}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load_source(path: Path, src_hint: str) -> list[dict]:
    samples: list[dict] = []
    if not path.exists():
        print(f"  [skip] {src_hint}: {path} missing")
        return samples
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue
            s["source_bucket"] = _classify_source(s, src_hint)
            samples.append(s)
    print(f"  {src_hint:20s} {len(samples):5d} from {path.name}")
    return samples


def qc_filter(samples: list[dict]) -> tuple[list[dict], Counter]:
    kept: list[dict] = []
    rejected = Counter()
    for s in samples:
        if _is_refusal(s):
            # refusals must have a non-empty assistant
            if len(_get_role(s, "assistant")) < 20:
                rejected["refusal_short"] += 1
                continue
            kept.append(s)
            continue
        if _is_partial_refusal(s):
            if not _partial_code_ok(_get_role(s, "assistant")):
                rejected["partial_code_bad"] += 1
                continue
            kept.append(s)
            continue
        # Normal CAD sample
        code = _get_role(s, "assistant")
        if not _code_quality_ok(code):
            rejected["code_quality"] += 1
            continue
        # user prompt non-empty
        if len(_get_role(s, "user")) < 5:
            rejected["empty_prompt"] += 1
            continue
        kept.append(s)
    return kept, rejected


def dedup(samples: list[dict]) -> tuple[list[dict], int]:
    seen: set[str] = set()
    out: list[dict] = []
    removed = 0
    for s in samples:
        k = _dedup_key(s)
        if k in seen:
            removed += 1
            continue
        seen.add(k)
        out.append(s)
    return out, removed


def split_90_5_5(samples: list[dict], rng: random.Random) -> tuple[list, list, list]:
    """Stratified 90/5/5 by source_bucket."""
    buckets: dict[str, list[dict]] = {}
    for s in samples:
        b = s.get("source_bucket", "other")
        buckets.setdefault(b, []).append(s)

    train: list[dict] = []
    val: list[dict] = []
    test: list[dict] = []
    for b, items in buckets.items():
        rng.shuffle(items)
        n = len(items)
        n_val = max(1, int(n * 0.05)) if n >= 20 else 0
        n_test = max(1, int(n * 0.05)) if n >= 20 else 0
        n_train = n - n_val - n_test
        train.extend(items[:n_train])
        val.extend(items[n_train:n_train + n_val])
        test.extend(items[n_train + n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test


def write_jsonl(path: Path, samples: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/build123d_ftc"),
    )
    ap.add_argument("--seed", type=int, default=90210)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    dd = args.data_dir

    print("=== Phase 6: load sources ===")
    all_samples: list[dict] = []
    all_samples += load_source(dd / "templates_valid.jsonl", "templates")
    all_samples += load_source(dd / "deepcad_valid.jsonl", "deepcad")
    all_samples += load_source(dd / "editing_valid.jsonl", "editing")
    all_samples += load_source(dd / "complex_valid.jsonl", "complex")
    all_samples += load_source(dd / "rejection_raw.jsonl", "rejection")
    print(f"  total loaded: {len(all_samples)}")

    print("\n=== QC filter ===")
    kept, rejected = qc_filter(all_samples)
    for k, v in rejected.items():
        print(f"  dropped {k:20s} {v}")
    print(f"  kept: {len(kept)} / {len(all_samples)}")

    print("\n=== Dedup ===")
    unique, dup_removed = dedup(kept)
    print(f"  removed duplicates: {dup_removed}")
    print(f"  unique: {len(unique)}")

    print("\n=== Bucket distribution (pre-split) ===")
    bucket_counts = Counter(s.get("source_bucket", "other") for s in unique)
    for b, c in sorted(bucket_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {b:25s} {c}")

    print("\n=== Split 90/5/5 ===")
    train, val, test = split_90_5_5(unique, rng)
    print(f"  train: {len(train)}")
    print(f"  val  : {len(val)}")
    print(f"  test : {len(test)}")

    out_dir = dd / "final"
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "val.jsonl", val)
    write_jsonl(out_dir / "test.jsonl", test)

    manifest = {
        "dataset": "orionflow_build123d_ftc",
        "total_samples": len(unique),
        "train": len(train),
        "val": len(val),
        "test": len(test),
        "buckets": dict(bucket_counts),
        "dropped_qc": dict(rejected),
        "duplicates_removed": dup_removed,
        "seed": args.seed,
    }
    with (out_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n=== Wrote to {out_dir} ===")
    print(f"  train.jsonl ({len(train)})")
    print(f"  val.jsonl   ({len(val)})")
    print(f"  test.jsonl  ({len(test)})")
    print(f"  manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
