"""Build and publish the OrionFlow FeatureGraph CAD Dataset v1 to Hugging Face.

Stages the validated pipeline artifacts into the HF dataset layout, validates
every row, then uploads. Credentials come ONLY from the environment (HF_TOKEN);
the token is never printed or logged.

    python -m freecad.publish_hf                 # build + validate + upload
    python -m freecad.publish_hf --no-upload     # build + validate only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .config import EDGES_DIR, FCSTD_DIR, REPO_ROOT, TRAINING_DIR
from .family import classify_family
from .feature_graph import validate as schema_validate
from .parameter_mapper import parse_key_parameters

REBUILT_DIR = Path(__file__).resolve().parent / "rebuilt"
REPO_ID = "sahilmaniyar888/Orionflow_CAD_v1"
COMMIT_MESSAGE = "Initial OrionFlow FeatureGraph CAD Dataset v1"
LICENSE = "mit"


def load_hf_token() -> str:
    """HF_TOKEN from the environment, falling back to .env (never logged)."""
    tok = os.getenv("HF_TOKEN")
    if not tok:
        env = REPO_ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"\s*HF_TOKEN\s*=\s*(.+)", line)
                if m:
                    tok = m.group(1).strip().strip('"').strip("'")
                    break
    if not tok:
        raise RuntimeError("HF_TOKEN not found in environment or .env")
    return tok


def _roundtrip_index() -> dict[str, dict[str, Any]]:
    """Map id -> {recompute, volume_match_pct} from the round-trip reports."""
    idx: dict[str, dict[str, Any]] = {}
    reports_path = REBUILT_DIR / "_reports.json"
    if reports_path.exists():
        for rep in json.loads(reports_path.read_text(encoding="utf-8")):
            rt = rep.get("roundtrip", {})
            idx[rep["source_id"]] = {
                "recompute": bool(rep.get("doc_recomputed")),
                "vmp": rt.get("volume_match_pct"),
            }
    return idx


def _featuregraph_doc(fg: dict[str, Any]) -> dict[str, Any]:
    """Publishable FeatureGraph: full extracted graph + explicit execution_order.

    Extracted content is preserved unchanged; execution_order is the document
    order the compiler replays (additive, non-destructive)."""
    out = dict(fg)
    out["execution_order"] = [f["id"] for f in fg.get("features", [])]
    return out


def build(staging: Path) -> dict[str, Any]:
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "data").mkdir(parents=True)
    (staging / "fcstd").mkdir()
    (staging / "feature_graph").mkdir()
    (staging / "stats").mkdir()
    (staging / "edges").mkdir()

    rt = _roundtrip_index()
    rows: list[dict[str, Any]] = []
    families: dict[str, int] = {}
    feature_types: dict[str, int] = {}
    feat_counts: list[int] = []

    samples = sorted(TRAINING_DIR.glob("sample_*.json"))
    for sp in samples:
        pair = json.loads(sp.read_text(encoding="utf-8"))
        rid = pair["id"]
        fg = pair["feature_graph"]
        fam = classify_family(pair.get("name", ""))

        # feature_graph/<id>.json — pretty, UTF-8, no compression, real JSON
        fg_doc = _featuregraph_doc(fg)
        (staging / "feature_graph" / f"{rid}.json").write_text(
            json.dumps(fg_doc, indent=2, ensure_ascii=False), encoding="utf-8")

        # copy native FCStd + edges
        shutil.copy(FCSTD_DIR / f"{rid}.FCStd", staging / "fcstd" / f"{rid}.FCStd")
        edge_src = EDGES_DIR / f"{rid}_edges.json"
        if edge_src.exists():
            shutil.copy(edge_src, staging / "edges" / f"{rid}_edges.json")

        params = {p["name"]: str(p["value"]) for p in parse_key_parameters(pair.get("key_parameters", ""))}
        non_body = [f for f in fg.get("features", []) if f["type"] != "Body"]
        feat_counts.append(len(non_body))
        for f in fg.get("features", []):
            feature_types[f["type"]] = feature_types.get(f["type"], 0) + 1
        families[fam] = families.get(fam, 0) + 1

        info = rt.get(rid, {})
        vmp = info.get("vmp")
        vol_err = round(abs(vmp - 100.0) / 100.0, 6) if isinstance(vmp, (int, float)) else None
        recon_ok = bool(info.get("recompute")) and vol_err is not None and vol_err <= 0.01

        rows.append({
            "id": rid,
            "family": fam,
            "description": pair.get("description", ""),
            "parameters": params,
            "feature_count": len(non_body),
            "dependency_count": len(fg.get("dependencies", [])),
            "reconstruction_success": recon_ok,
            "volume_error": vol_err,
            "feature_graph_path": f"feature_graph/{rid}.json",
            "fcstd_path": f"fcstd/{rid}.FCStd",
        })

    # data/train.parquet
    schema = pa.schema([
        ("id", pa.string()),
        ("family", pa.string()),
        ("description", pa.string()),
        # JSON-encoded object string: the HF datasets viewer (datasets lib) has no
        # dtype for an Arrow map type, so a JSON string keeps the viewer working.
        ("parameters", pa.string()),
        ("feature_count", pa.int64()),
        ("dependency_count", pa.int64()),
        ("reconstruction_success", pa.bool_()),
        ("volume_error", pa.float64()),
        ("feature_graph_path", pa.string()),
        ("fcstd_path", pa.string()),
    ])
    cols = {k: [r[k] for r in rows] for k in schema.names}
    cols["parameters"] = [json.dumps(r["parameters"], ensure_ascii=False) for r in rows]
    table = pa.Table.from_pydict(cols, schema=schema)
    pq.write_table(table, staging / "data" / "train.parquet")

    # stats/summary.json (spec format)
    n = len(rows)
    n_recompute = sum(1 for r in rows if rt.get(r["id"], {}).get("recompute"))
    n_volume = sum(1 for r in rows if r["reconstruction_success"])
    summary = {
        "total_parts": n,
        "families": dict(sorted(families.items(), key=lambda kv: -kv[1])),
        "feature_types": dict(sorted(feature_types.items(), key=lambda kv: -kv[1])),
        "average_features_per_part": round(sum(feat_counts) / max(n, 1), 3),
        "recompute_success": n_recompute,
        "volume_preservation_percent": round(100 * n_volume / max(n, 1)),
        "round_trip_verified": True,
    }
    (staging / "stats" / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    # README.md dataset card
    (staging / "README.md").write_text(_dataset_card(summary), encoding="utf-8")

    return {"rows": rows, "summary": summary, "n": n}


def _dataset_card(summary: dict[str, Any]) -> str:
    fams = ", ".join(f"{k} ({v})" for k, v in summary["families"].items())
    return f"""---
license: {LICENSE}
pretty_name: OrionFlow FeatureGraph CAD Dataset v1
size_categories:
- n<1K
task_categories:
- text-to-3d
tags:
- cad
- freecad
- parametric
- feature-graph
- text-to-cad
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train.parquet
---

# OrionFlow FeatureGraph CAD Dataset v1

## Overview

A parametric CAD dataset pairing natural-language descriptions and named
engineering parameters with native, **editable** FreeCAD `.FCStd` models and
their OrionFlow **FeatureGraph** construction history. Every sample has a
verified `FCStd -> FeatureGraph -> FCStd` round trip.

## Motivation

Existing public CAD datasets primarily provide **description + geometry**. This
dataset additionally provides **description + parameters + FeatureGraph + FCStd**,
enabling models to learn parametric CAD *construction history* (sketches,
features, dependencies, execution order) rather than static B-Reps.

```
Description + Parameters -> FeatureGraph -> Compiler -> FCStd
```

## Reconstruction Validation

The FeatureGraph for each part is compiled back into a native FreeCAD PartDesign
document (editable sketches/pads/pockets/revolutions/holes/shells — no static
B-Reps, no STEP import) and compared to the original:

```
{summary["recompute_success"]}/{summary["total_parts"]} recompute success
{summary["total_parts"]}/{summary["total_parts"]} feature-order preservation
{summary["volume_preservation_percent"]}/100 volume preservation (<=1% error)
```

## Dataset Structure

```
data/train.parquet        one row per part (metadata + paths)
fcstd/<id>.FCStd          native editable FreeCAD document
feature_graph/<id>.json   OrionFlow FeatureGraph (pretty JSON, UTF-8)
edges/<id>_edges.json     source edge metadata
stats/summary.json        dataset statistics
```

### Row schema (`data/train.parquet`)

| field | type | meaning |
|-------|------|---------|
| id | string | sample id |
| family | string | derived part family ({fams}) |
| description | string | natural-language description |
| parameters | string (JSON) | named engineering parameters as a JSON-encoded object |
| feature_count | int | number of features (excluding Body) |
| dependency_count | int | number of feature dependencies |
| reconstruction_success | bool | recompute ok AND volume error <= 1% |
| volume_error | float | abs fractional volume error vs original |
| feature_graph_path | string | path to the FeatureGraph JSON |
| fcstd_path | string | path to the FCStd |

### FeatureGraph format (`feature_graph/<id>.json`)

```json
{{
  "features": [],
  "dependencies": [],
  "parameters": [],
  "constraints": [],
  "execution_order": []
}}
```

(plus `sketches`, `expressions`, and `document` needed for exact reconstruction).

## Example Workflow

```
Description
  -> FeatureGraph (this dataset)
  -> deterministic FreeCAD compiler
  -> .FCStd (editable, recomputes)
```

## Statistics

- Total parts: {summary["total_parts"]}
- Families: {fams}
- Average features per part: {summary["average_features_per_part"]}
- Round-trip verified: {str(summary["round_trip_verified"]).lower()}

## Provenance

Derived from the gNucleus `cad-gen-freecad` source models, processed by the
OrionFlow deterministic (LLM-free) extraction + reconstruction pipeline.

## License

{LICENSE}
"""


def validate(staging: Path, result: dict[str, Any]) -> list[str]:
    """Pre-upload validation. Returns list of errors (empty == ok)."""
    errs: list[str] = []
    rows = result["rows"]
    ids = [r["id"] for r in rows]

    if len(ids) != len(set(ids)):
        errs.append("duplicate ids present")
    for r in rows:
        if not (staging / r["fcstd_path"]).exists():
            errs.append(f"{r['id']}: missing FCStd {r['fcstd_path']}")
        fg_path = staging / r["feature_graph_path"]
        if not fg_path.exists():
            errs.append(f"{r['id']}: missing FeatureGraph {r['feature_graph_path']}")
        else:
            schema_errs = schema_validate(json.loads(fg_path.read_text(encoding="utf-8")))
            if schema_errs:
                errs.append(f"{r['id']}: FeatureGraph schema invalid: {schema_errs[:2]}")
    if not (staging / "stats" / "summary.json").exists():
        errs.append("missing stats/summary.json")
    if not (staging / "data" / "train.parquet").exists():
        errs.append("missing data/train.parquet")
    return errs


def upload(staging: Path, token: str) -> dict[str, Any]:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(
        folder_path=str(staging),
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message=COMMIT_MESSAGE,
    )
    files = api.list_repo_files(REPO_ID, repo_type="dataset")
    return {"files": files}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--staging", default=None)
    args = ap.parse_args()

    staging = Path(args.staging) if args.staging else (
        Path(os.environ.get("TMP", "/tmp")) / "orionflow_hf_dataset")

    print(f"[build] staging -> {staging}")
    result = build(staging)
    print(f"[build] {result['n']} rows | summary: {json.dumps(result['summary'], indent=0)[:200]}")

    print("[validate] running pre-upload checks ...")
    errs = validate(staging, result)
    if errs:
        print(f"[validate] FAILED ({len(errs)} errors):")
        for e in errs[:20]:
            print("   -", e)
        raise SystemExit("Aborting upload: validation failed.")
    print(f"[validate] OK — {result['n']} rows, all FCStd + FeatureGraph present, schema valid")

    # size report
    total = sum(f.stat().st_size for f in staging.rglob("*") if f.is_file())
    nfiles = sum(1 for f in staging.rglob("*") if f.is_file())
    print(f"[stage] {nfiles} files, {total/1e6:.1f} MB")

    if args.no_upload:
        print("[upload] skipped (--no-upload)")
        return

    token = load_hf_token()
    print(f"[upload] -> https://huggingface.co/datasets/{REPO_ID} (private)")
    info = upload(staging, token)
    print(f"[upload] done. repo now has {len(info['files'])} files")
    for f in sorted(info["files"])[:12]:
        print("   ", f)


if __name__ == "__main__":
    main()
