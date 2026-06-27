"""Measurable, non-heuristic dataset-quality metrics for a FeatureGraph.

Every metric here is a *counted ratio* over what the extractor actually found —
not an inferred opinion. Reconstruction success is intentionally absent: it is
measured by ``roundtrip_validate`` (it requires launching FreeCAD), and is
merged in there. Standalone (no FreeCAD, no heavy deps).
"""

from __future__ import annotations

import re
from typing import Any

_AUTONAME = re.compile(r"^\d+$")


def _is_named(feat: dict[str, Any]) -> bool:
    """A feature is 'named' if its label carries intent rather than the FreeCAD
    default (``Pad``, ``Pocket001``, ``Sketch002`` == type + optional digits)."""
    label = (feat.get("label") or "").strip()
    if not label or label == feat.get("id"):
        return False
    typ = feat.get("type", "")
    if label == typ:
        return False
    if typ and re.match(r"^" + re.escape(typ) + r"\d*$", label):
        return False
    return True


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 2) if den else 0.0


def score_graph(graph: dict[str, Any], multimodal: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return measured quality percentages for one extracted model."""
    feats = [f for f in graph.get("features", []) if f.get("type") != "Body"]
    sketches = graph.get("sketches", [])
    exprs = graph.get("expressions", [])
    params = graph.get("parameters", [])
    mm = multimodal or {}

    # Spreadsheet-driven: expressions whose referenced object is a Spreadsheet.
    sheet_ids = {f["id"] for f in graph.get("features", [])
                 if "Spreadsheet" in f.get("type_id", "")}
    sheet_ids |= {f["label"] for f in graph.get("features", [])
                  if "Spreadsheet" in f.get("type_id", "")}
    expr_objs = {e["object"] for e in exprs}
    sheet_driven = [e for e in exprs
                    if any(r in sheet_ids for r in e.get("referenced_objects", []))]

    # Fully-constrained sketches from the multimodal sub-graphs (has DoF).
    subg = mm.get("sketch_subgraphs", [])
    constrained = [s for s in subg if s.get("fully_constrained") is True]

    ext_sketches = [s for s in sketches if s.get("external_geometry")]
    bound_params = [p for p in params if p.get("bound_to")]
    typed_feats = [f for f in feats if f.get("type") != "Other"]

    return {
        "n_features": len(feats),
        "n_sketches": len(sketches),
        "features_named_pct": _pct(sum(_is_named(f) for f in feats), len(feats)),
        "expression_coverage_pct": _pct(len(expr_objs & {f["id"] for f in feats}), len(feats)),
        "spreadsheet_driven_pct": _pct(len(sheet_driven), len(exprs)) if exprs else 0.0,
        "fully_constrained_pct": _pct(len(constrained), len(subg)) if subg else 0.0,
        "external_geometry_pct": _pct(len(ext_sketches), len(sketches)) if sketches else 0.0,
        "param_coverage_pct": _pct(len(bound_params), len(params)) if params else 0.0,
        "parser_confidence_pct": _pct(len(typed_feats), len(feats)),
    }
