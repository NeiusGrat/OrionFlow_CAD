"""Phase 3 — round-trip validation across a family (default: flange).

    FCStd -> FeatureGraph -> Compiler -> FCStd

Selects samples by family, reconstructs them via the FreeCAD-side compiler, and
aggregates: reconstruction success, recompute success, volume preservation,
feature-order preservation.

    python -m freecad.roundtrip_validate --family flange
    python -m freecad.roundtrip_validate --family all        # every sample
    python -m freecad.roundtrip_validate --buildable         # only Sketch/Pad/Pocket parts
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
from pathlib import Path
from typing import Any

from .config import FCSTD_DIR, PKG_DIR, TRAINING_DIR, ensure_dirs, find_freecad_python
from .family import classify_family

REBUILT_DIR = PKG_DIR / "rebuilt"
RECONSTRUCT_SCRIPT = PKG_DIR / "reconstruct.py"
SUPPORTED = {"Body", "Sketch", "Pad", "Pocket", "Revolution", "Groove"}
VOLUME_TOL_PCT = 1.0  # within 1% counts as preserved


def _select(family: str | None, buildable: bool) -> list[dict[str, Any]]:
    rows = []
    for f in sorted(glob.glob(str(TRAINING_DIR / "sample_*.json"))):
        p = json.load(open(f, encoding="utf-8"))
        fam = classify_family(p.get("name", ""))
        types = {ft["type"] for ft in p["feature_graph"].get("features", [])}
        if buildable and not types <= SUPPORTED:
            continue
        if family and family != "all" and fam != family:
            continue
        rows.append({"id": p["id"], "graph_path": f, "family": fam,
                     "types": sorted(types)})
    return rows


def run(family: str = "flange", buildable: bool = False) -> dict[str, Any]:
    ensure_dirs()
    REBUILT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _select(family, buildable)
    print(f"[select] {len(rows)} samples (family={family}, buildable_only={buildable})")
    if not rows:
        return {"n": 0}

    manifest = [{"id": r["id"], "graph": r["graph_path"],
                 "original_fcstd": str(FCSTD_DIR / f"{r['id']}.FCStd")} for r in rows]
    manifest_path = REBUILT_DIR / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    freecad_py = find_freecad_python()
    cmd = [freecad_py, str(RECONSTRUCT_SCRIPT), "--manifest", str(manifest_path),
           "--out-dir", str(REBUILT_DIR), "--roundtrip"]
    print(f"[compile] {freecad_py} -> {REBUILT_DIR}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("[compile] STDERR tail:\n" + (proc.stderr or "")[-1500:])
        raise RuntimeError(f"reconstruction failed rc={proc.returncode}")

    reports = json.loads((REBUILT_DIR / "_reports.json").read_text(encoding="utf-8"))

    summary = {
        "family": family, "buildable_only": buildable, "n": len(reports),
        "reconstructed": 0, "recomputed": 0, "order_preserved": 0,
        "volume_preserved": 0, "with_volume_cmp": 0, "failures": [],
    }
    for rep in reports:
        rid = rep["source_id"]
        if rep.get("final_object_count", 0) > 1:
            summary["reconstructed"] += 1
        if rep.get("doc_recomputed"):
            summary["recomputed"] += 1
        rt = rep.get("roundtrip", {})
        if rt.get("solid_order_preserved"):
            summary["order_preserved"] += 1
        vmp = rt.get("volume_match_pct")
        if vmp is not None:
            summary["with_volume_cmp"] += 1
            if abs(vmp - 100.0) <= VOLUME_TOL_PCT:
                summary["volume_preserved"] += 1
            else:
                summary["failures"].append({"id": rid, "volume_match_pct": vmp,
                                            "unsupported": rep.get("unsupported", [])})
        if not rep.get("doc_recomputed") or rep.get("recompute_errors"):
            summary["failures"].append({"id": rid, "recompute_errors": rep.get("recompute_errors"),
                                        "unsupported": rep.get("unsupported", [])})

    n = summary["n"]
    summary["recompute_rate"] = round(summary["recomputed"] / n, 4)
    summary["order_rate"] = round(summary["order_preserved"] / n, 4)
    vc = max(summary["with_volume_cmp"], 1)
    summary["volume_preserved_rate"] = round(summary["volume_preserved"] / vc, 4)
    (REBUILT_DIR / "roundtrip_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="flange")
    ap.add_argument("--buildable", action="store_true")
    args = ap.parse_args()
    s = run(family=args.family, buildable=args.buildable)
    print("\n===== ROUND-TRIP SUMMARY =====")
    print(json.dumps({k: v for k, v in s.items() if k != "failures"}, indent=2))
    if s.get("failures"):
        print(f"\n{len(s['failures'])} failures (see rebuilt/roundtrip_summary.json)")


if __name__ == "__main__":
    main()
