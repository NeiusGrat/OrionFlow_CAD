"""Validation ladder for extracted FeatureGraphs.

Two layers here (schema + internal integrity + parameter coverage). The heavier
round-trip check (FeatureGraph -> FreeCAD -> re-extract -> compare counts) lives
in ``reconstruct.py`` so the cheap checks can run without launching FreeCAD.
"""

from __future__ import annotations

from typing import Any

from .feature_graph import validate as schema_validate


def integrity_errors(graph: dict[str, Any]) -> list[str]:
    """Referential-integrity checks within a single graph."""
    errs: list[str] = []
    feature_ids = {f["id"] for f in graph.get("features", [])}
    sketch_ids = {s["id"] for s in graph.get("sketches", [])}

    for s in sketch_ids:
        if s not in feature_ids:
            errs.append(f"sketch '{s}' has no matching feature entry")

    for i, d in enumerate(graph.get("dependencies", [])):
        if d["source"] not in feature_ids:
            errs.append(f"dependencies[{i}]: unknown source '{d['source']}'")
        if d["target"] not in feature_ids:
            errs.append(f"dependencies[{i}]: unknown target '{d['target']}'")

    for i, e in enumerate(graph.get("expressions", [])):
        if e["object"] not in feature_ids:
            errs.append(f"expressions[{i}]: unknown object '{e['object']}'")

    for i, p in enumerate(graph.get("parameters", [])):
        for j, b in enumerate(p.get("bound_to", [])):
            tgt = b["target"].split(":")[0]
            if tgt not in feature_ids and tgt not in sketch_ids:
                errs.append(f"parameters[{i}].bound_to[{j}]: unknown target '{b['target']}'")
    return errs


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Full single-graph validation report."""
    schema_errs = schema_validate(graph)
    integ_errs = integrity_errors(graph)
    params = graph.get("parameters", [])
    bound = [p for p in params if p.get("bound_to")]
    return {
        "schema_errors": schema_errs,
        "integrity_errors": integ_errs,
        "n_features": len(graph.get("features", [])),
        "n_sketches": len(graph.get("sketches", [])),
        "n_dependencies": len(graph.get("dependencies", [])),
        "n_params": len(params),
        "n_params_bound": len(bound),
        "param_coverage": round(len(bound) / len(params), 4) if params else 0.0,
        "valid": not schema_errs and not integ_errs,
    }
