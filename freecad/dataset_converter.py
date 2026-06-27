"""Orchestrator: dataset rows -> FeatureGraph training pairs (end to end).

System-Python side. Coordinates download, the FreeCAD-subprocess extraction,
parameter recovery, graph assembly, validation, and training-pair output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import download_dataset
from .config import (
    FCSTD_DIR,
    PKG_DIR,
    RAW_EXTRACT_DIR,
    TRAINING_DIR,
    ensure_dirs,
    find_freecad_python,
)
from .feature_graph import build_graph
from .parameter_mapper import map_parameters
from .quality import score_graph
from .validate import validate_graph

PARSER_SCRIPT = PKG_DIR / "fcstd_multimodal.py"


def _run_freecad_extraction(manifest: list[dict[str, str]]) -> str:
    """Invoke the multimodal extractor under FreeCAD's Python over the manifest.

    Output per file is ``<id>.multimodal.json`` — a superset of the base raw
    graph plus the four GNN layers. The base raw is recovered downstream by
    popping the ``multimodal`` block off."""
    ensure_dirs()
    manifest_path = RAW_EXTRACT_DIR / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    freecad_py = find_freecad_python()
    cmd = [freecad_py, str(PARSER_SCRIPT), "--manifest", str(manifest_path),
           "--out", str(RAW_EXTRACT_DIR)]
    print(f"[extract] {freecad_py}\n[extract] {len(manifest)} files -> {RAW_EXTRACT_DIR}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        tail = proc.stdout.strip().splitlines()[-3:]
        print("[extract] " + " | ".join(tail))
    if proc.returncode != 0:
        print("[extract] STDERR:\n" + (proc.stderr or "")[-2000:])
        raise RuntimeError(f"FreeCAD extraction failed (rc={proc.returncode})")
    return freecad_py


def run(limit: int = 100, with_glb: bool = False, skip_download: bool = False,
        skip_extract: bool = False) -> dict[str, Any]:
    ensure_dirs()
    rows = download_dataset.load_rows(limit=limit)
    print(f"[load] {len(rows)} rows")

    if not skip_download and not skip_extract:
        st = download_dataset.download_assets(rows, with_glb=with_glb)
        print(f"[download] {st}")

    # Manifest of rows whose FCStd is present locally.
    manifest, missing = [], []
    for r in rows:
        p = FCSTD_DIR / f"{r['id']}.FCStd"
        if p.exists():
            manifest.append({"id": r["id"], "fcstd": str(p)})
        else:
            missing.append(r["id"])
    if missing:
        print(f"[load] {len(missing)} FCStd missing, skipped: {missing[:5]}...")

    if skip_extract:
        print(f"[extract] skipped, reusing {RAW_EXTRACT_DIR}")
    else:
        _run_freecad_extraction(manifest)

    # Assemble training pairs.
    dataset_path = TRAINING_DIR / "dataset.jsonl"
    summary = {
        "n_rows": len(rows), "n_extracted": 0, "n_extract_errors": 0,
        "n_valid": 0, "n_invalid": 0, "param_coverage_sum": 0.0, "n_param_rows": 0,
        "errors": [], "low_coverage": [],
    }
    with dataset_path.open("w", encoding="utf-8") as ds:
        for idx, r in enumerate(rows, 1):
            rid = r["id"]
            raw_path = RAW_EXTRACT_DIR / f"{rid}.multimodal.json"
            if not raw_path.exists():
                summary["n_extract_errors"] += 1
                summary["errors"].append({"id": rid, "error": "no raw output"})
                continue
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            if "error" in raw:
                summary["n_extract_errors"] += 1
                summary["errors"].append({"id": rid, "error": raw["error"]})
                continue
            summary["n_extracted"] += 1

            # Separate the GNN multimodal layers from the schema-validated graph.
            multimodal = raw.pop("multimodal", {})
            params, pstats = map_parameters(raw, r.get("key_parameters", ""))
            graph = build_graph(raw, params)
            quality = score_graph(graph, multimodal)
            report = validate_graph(graph)
            if report["valid"]:
                summary["n_valid"] += 1
            else:
                summary["n_invalid"] += 1
                summary["errors"].append({"id": rid, "error": "validation",
                                          "detail": (report["schema_errors"] + report["integrity_errors"])[:5]})
            summary["param_coverage_sum"] += pstats["coverage"]
            summary["n_param_rows"] += 1
            if pstats["coverage"] < 1.0:
                summary["low_coverage"].append({"id": rid, "coverage": pstats["coverage"],
                                                "unbound": pstats["unbound_names"]})

            pair = {
                "id": rid,
                "name": r.get("name", ""),
                "description": r.get("description", ""),
                "key_parameters": r.get("key_parameters", ""),
                "feature_graph": graph,
                "multimodal": multimodal,
                "quality": quality,
                "_meta": {"param_stats": pstats, "validation": report},
            }
            sample_path = TRAINING_DIR / f"sample_{idx:04d}_{rid}.json"
            sample_path.write_text(json.dumps(pair, indent=2), encoding="utf-8")
            ds.write(json.dumps({k: pair[k] for k in
                                 ("id", "description", "key_parameters", "feature_graph", "multimodal")}) + "\n")

    n = max(summary["n_param_rows"], 1)
    summary["mean_param_coverage"] = round(summary["param_coverage_sum"] / n, 4)
    (TRAINING_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    s = run(limit=limit)
    print(json.dumps({k: v for k, v in s.items()
                      if k not in ("errors", "low_coverage")}, indent=2))
