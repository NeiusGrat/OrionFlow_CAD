"""
Pre-Phase-2 filter, dedup, and chunk splitter.
Pure Python — zero CAD dependencies.

Filters applied (in order):
  1. Code-level deduplication (MD5 of code string, keep first)
  2. Tiny geometry: diameter < 1.0 mm or thickness < 0.5 mm
  3. Zero/negative wall: any cutout diameter >= outer diameter
  4. Duplicate cutout lines in same sketch (identical .circle(x).cut())
  5. Cutout larger than part: cutout radius > outer radius * 0.95
  6. Code too short (< 80 chars) or too long (> 2000 chars)

Then splits clean output into N_CHUNKS files for GitHub Actions.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).resolve().parent
INPUT_FILE    = PROJECT_ROOT / "data" / "training" / "ofl_candidates.jsonl"
CLEAN_FILE    = PROJECT_ROOT / "data" / "training" / "ofl_candidates_clean.jsonl"
CHUNKS_DIR    = PROJECT_ROOT / "data" / "training" / "chunks"
REPORT_FILE   = PROJECT_ROOT / "data" / "training" / "preflight_report.json"

N_CHUNKS      = 20
MIN_DIAMETER  = 0.2    # mm — DeepCAD normalized coords, 50x scale; 0.2mm = raw 0.004
MIN_THICKNESS = 0.1    # mm — DeepCAD units are normalized, 50x scale means thin parts are common
MAX_CODE_LEN  = 2000   # chars
MIN_CODE_LEN  = 80     # chars


# ── Filter functions (each returns reason string or None if OK) ─


def _check_too_short_or_long(code: str) -> str | None:
    if len(code) < MIN_CODE_LEN:
        return f"code too short ({len(code)} chars)"
    if len(code) > MAX_CODE_LEN:
        return f"code too long ({len(code)} chars)"
    return None


def _check_missing_boilerplate(code: str) -> str | None:
    if "from orionflow_ofl import" not in code:
        return "missing import"
    if "export(" not in code:
        return "missing export"
    if "Sketch(" not in code:
        return "missing Sketch"
    if ".extrude(" not in code:
        return "missing extrude"
    return None


def _parse_outer_diameter(code: str) -> float | None:
    """Extract outer diameter from 'diameter = X.X' line."""
    m = re.search(r"^diameter\s*=\s*([\d.]+)", code, re.MULTILINE)
    if m:
        return float(m.group(1))
    return None


def _parse_outer_rect(code: str) -> tuple[float, float] | None:
    """Extract width/height from rect-based code."""
    w = re.search(r"^width\s*=\s*([\d.]+)", code, re.MULTILINE)
    h = re.search(r"^height\s*=\s*([\d.]+)", code, re.MULTILINE)
    if w and h:
        return float(w.group(1)), float(h.group(1))
    return None


def _parse_thickness(code: str) -> float | None:
    m = re.search(r"^thickness\s*=\s*([\d.]+)", code, re.MULTILINE)
    if m:
        return float(m.group(1))
    return None


def _parse_cutout_diameters(code: str) -> list[float]:
    """Extract all .circle(X).cut() diameters."""
    return [float(m) for m in re.findall(r"\.circle\(([\d.]+)\)\.cut\(\)", code)]


def _check_tiny_geometry(code: str) -> str | None:
    thickness = _parse_thickness(code)
    if thickness is not None and thickness < MIN_THICKNESS:
        return f"thickness too small ({thickness} mm)"

    outer_dia = _parse_outer_diameter(code)
    if outer_dia is not None and outer_dia < MIN_DIAMETER:
        return f"diameter too small ({outer_dia} mm)"

    outer_rect = _parse_outer_rect(code)
    if outer_rect is not None:
        w, h = outer_rect
        if w < MIN_DIAMETER or h < MIN_DIAMETER:
            return f"rect dimension too small ({w}x{h} mm)"

    return None


def _check_cutout_geometry(code: str) -> str | None:
    """Detect zero-wall and oversized cutouts."""
    cutout_dias = _parse_cutout_diameters(code)
    if not cutout_dias:
        return None

    # Check for duplicate cutouts (identical diameters cut twice)
    seen: dict[float, int] = {}
    for d in cutout_dias:
        seen[d] = seen.get(d, 0) + 1
    duplicates = {d: count for d, count in seen.items() if count > 1}
    if duplicates:
        return f"duplicate cutout diameters: {duplicates}"

    # Check against outer diameter
    outer_dia = _parse_outer_diameter(code)
    if outer_dia is not None:
        for d in cutout_dias:
            if d >= outer_dia * 0.95:
                return f"cutout diameter {d} >= 95% of outer diameter {outer_dia}"
            # Cutout larger than outer is always invalid
            if d > outer_dia:
                return f"cutout diameter {d} exceeds outer diameter {outer_dia}"

    # Check against rect: each cutout must be smaller than both rect dims
    outer_rect = _parse_outer_rect(code)
    if outer_rect is not None:
        w, h = outer_rect
        min_dim = min(w, h)
        for d in cutout_dias:
            if d >= min_dim * 0.95:
                return f"cutout diameter {d} too large for rect {w}x{h}"

    return None


def _check_negative_extrude_via_hole(code: str) -> str | None:
    """Catch .to_depth(X) where X <= 0."""
    for m in re.findall(r"\.to_depth\(([-\d.]+)\)", code):
        if float(m) <= 0:
            return f"non-positive hole depth: {m}"
    return None


ALL_CHECKS = [
    _check_missing_boilerplate,
    _check_too_short_or_long,
    _check_tiny_geometry,
    _check_cutout_geometry,
    _check_negative_extrude_via_hole,
]


def _code_hash(code: str) -> str:
    return hashlib.md5(code.encode()).hexdigest()


def main() -> None:
    if not INPUT_FILE.exists():
        print(f"ERROR: input not found: {INPUT_FILE}")
        sys.exit(1)

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Read all candidates ───────────────────────────────────
    raw_lines = INPUT_FILE.read_text(encoding="utf-8").splitlines()
    total_in = len(raw_lines)
    print(f"Loaded {total_in:,} candidates from {INPUT_FILE.name}")

    # ── Filter pass ──────────────────────────────────────────
    seen_hashes: set[str] = set()
    clean_pairs: list[dict] = []

    rejection_counts: dict[str, int] = {}

    for line in raw_lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            rejection_counts["invalid_json"] = rejection_counts.get("invalid_json", 0) + 1
            continue

        code = obj.get("code", "")

        # Deduplication
        h = _code_hash(code)
        if h in seen_hashes:
            rejection_counts["duplicate"] = rejection_counts.get("duplicate", 0) + 1
            continue
        seen_hashes.add(h)

        # Run all checks
        rejected = False
        for check_fn in ALL_CHECKS:
            reason = check_fn(code)
            if reason:
                rejection_counts[reason[:60]] = rejection_counts.get(reason[:60], 0) + 1
                rejected = True
                break

        if not rejected:
            clean_pairs.append(obj)

    total_clean = len(clean_pairs)
    total_removed = total_in - total_clean
    removal_rate = total_removed / total_in * 100 if total_in else 0

    print(f"\nFilter results:")
    print(f"  Input   : {total_in:,}")
    print(f"  Clean   : {total_clean:,}  ({100 - removal_rate:.1f}% kept)")
    print(f"  Removed : {total_removed:,}  ({removal_rate:.1f}%)")
    print(f"\nRejection breakdown (top 15):")
    for reason, count in sorted(rejection_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {count:6,}  {reason}")

    # ── Write clean JSONL ─────────────────────────────────────
    with CLEAN_FILE.open("w", encoding="utf-8") as f:
        for obj in clean_pairs:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"\nWrote clean file: {CLEAN_FILE.name}  ({CLEAN_FILE.stat().st_size / 1e6:.1f} MB)")

    # ── Split into chunks ─────────────────────────────────────
    chunk_size = max(1, (total_clean + N_CHUNKS - 1) // N_CHUNKS)
    chunk_files_written = []

    for i in range(N_CHUNKS):
        chunk = clean_pairs[i * chunk_size : (i + 1) * chunk_size]
        chunk_path = CHUNKS_DIR / f"chunk_{i:03d}.jsonl"
        with chunk_path.open("w", encoding="utf-8") as f:
            for obj in chunk:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        chunk_files_written.append({"file": chunk_path.name, "lines": len(chunk)})

    print(f"\nChunks written to {CHUNKS_DIR}/")
    for c in chunk_files_written:
        print(f"  {c['file']}  ->  {c['lines']:,} samples")

    # ── Write report ─────────────────────────────────────────
    report = {
        "input_file":      str(INPUT_FILE),
        "clean_file":      str(CLEAN_FILE),
        "chunks_dir":      str(CHUNKS_DIR),
        "total_in":        total_in,
        "total_clean":     total_clean,
        "total_removed":   total_removed,
        "kept_pct":        round(100 - removal_rate, 2),
        "rejection_counts": dict(sorted(rejection_counts.items(), key=lambda x: -x[1])),
        "chunks":          chunk_files_written,
        "n_chunks":        N_CHUNKS,
        "chunk_size":      chunk_size,
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    print(f"\nReport saved: {REPORT_FILE.name}")

    # ── Final verdict ─────────────────────────────────────────
    print("\n" + "=" * 55)
    if total_clean >= 50_000:
        print(f"  READY FOR PHASE 2: {total_clean:,} clean samples")
    elif total_clean >= 30_000:
        print(f"  BORDERLINE: {total_clean:,} clean samples (target was 50k)")
        print("   Consider lowering MIN_DIAMETER to 0.5 to recover more.")
    else:
        print(f"  TOO FEW: only {total_clean:,} clean samples")
        print("   Lower MIN_DIAMETER / MIN_THICKNESS thresholds and re-run.")
    print("=" * 55)


if __name__ == "__main__":
    main()
