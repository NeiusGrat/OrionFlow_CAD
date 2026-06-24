"""Phase 1 — dataset statistics over extracted FeatureGraphs.

Reads ``training/sample_*.json`` and emits ``training/feature_graph_stats.json``:
feature/family/parameter frequencies, graph depth, ordered feature-sequence
patterns, the full operation vocabulary, and a reconstruction-coverage report
(which parts are buildable by a given supported operation set).
"""

from __future__ import annotations

import glob
import json
from collections import Counter, defaultdict
from typing import Any

from .config import TRAINING_DIR
from .family import classify_family

# Operations the flange compiler supported first (Phase 2).
FLANGE_VOCAB = {"Body", "Sketch", "Pad", "Pocket"}
# Operations supported after Phase 4/5 expansion (BSpline geometry + Revolution/
# Groove/Hole/Thickness). Note: PolarPattern/LinearPattern/Fillet/Chamfer do NOT
# occur in this dataset; the real gaps were BSpline geometry and turned/shelled parts.
EXTENDED_VOCAB = FLANGE_VOCAB | {"Revolution", "Groove", "Hole", "Thickness"}


def _load_pairs() -> list[dict[str, Any]]:
    pairs = []
    for f in sorted(glob.glob(str(TRAINING_DIR / "sample_*.json"))):
        pairs.append(json.load(open(f, encoding="utf-8")))
    return pairs


def _graph_depth(graph: dict[str, Any]) -> int:
    """Longest path length through the dependency DAG (in edges)."""
    succ: dict[str, list[str]] = defaultdict(list)
    nodes = {f["id"] for f in graph.get("features", [])}
    for d in graph.get("dependencies", []):
        succ[d["source"]].append(d["target"])
    memo: dict[str, int] = {}

    def depth(n: str, seen: frozenset) -> int:
        if n in memo:
            return memo[n]
        best = 0
        for m in succ.get(n, []):
            if m in seen:
                continue
            best = max(best, 1 + depth(m, seen | {m}))
        memo[n] = best
        return best

    return max((depth(n, frozenset({n})) for n in nodes), default=0)


def _op_sequence(graph: dict[str, Any]) -> list[str]:
    """Feature types in document order, excluding the Body container."""
    return [f["type"] for f in graph.get("features", []) if f["type"] != "Body"]


def _solid_op_sequence(graph: dict[str, Any]) -> list[str]:
    """Only the solid operations (drops sketches), e.g. Pad->Pocket->Pocket."""
    return [f["type"] for f in graph.get("features", [])
            if f["type"] not in ("Body", "Sketch")]


def compute_stats(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    feature_freq: Counter = Counter()
    family_freq: Counter = Counter()
    param_freq: Counter = Counter()
    seq_patterns: Counter = Counter()
    solid_seq_patterns: Counter = Counter()
    geom_freq: Counter = Counter()
    depths: list[int] = []
    feats_per_part: list[int] = []
    family_feats: dict[str, Counter] = defaultdict(Counter)
    family_coverage: dict[str, list[float]] = defaultdict(list)

    flange_buildable = extended_buildable = 0

    for p in pairs:
        g = p["feature_graph"]
        fam = classify_family(p.get("name", ""))
        family_freq[fam] += 1

        types = [f["type"] for f in g.get("features", [])]
        for t in types:
            feature_freq[t] += 1
            family_feats[fam][t] += 1
        feats_per_part.append(len([t for t in types if t != "Body"]))
        depths.append(_graph_depth(g))

        seq = _op_sequence(g)
        seq_patterns[" -> ".join(seq)] += 1
        solid_seq_patterns[" -> ".join(_solid_op_sequence(g))] += 1

        for sk in g.get("sketches", []):
            for geo in sk.get("geometry", []):
                geom_freq[geo.get("type", "?")] += 1

        for pr in g.get("parameters", []):
            param_freq[pr["name"]] += 1

        # Coverage = fraction of params with a geometry binding.
        params = g.get("parameters", [])
        bound = sum(1 for pr in params if pr.get("bound_to"))
        family_coverage[fam].append(bound / len(params) if params else 1.0)

        type_set = set(types)
        if type_set <= FLANGE_VOCAB:
            flange_buildable += 1
        if type_set <= EXTENDED_VOCAB:
            extended_buildable += 1

    n = len(pairs)
    family_mean_cov = {
        fam: round(sum(c) / len(c), 4) for fam, c in family_coverage.items()
    }

    return {
        "n_parts": n,
        "feature_frequency": dict(feature_freq.most_common()),
        "family_frequency": dict(family_freq.most_common()),
        "parameter_frequency": dict(param_freq.most_common()),
        "geometry_frequency": dict(geom_freq.most_common()),
        "average_graph_depth": round(sum(depths) / max(n, 1), 3),
        "max_graph_depth": max(depths, default=0),
        "average_features_per_part": round(sum(feats_per_part) / max(n, 1), 3),
        "feature_sequence_patterns": dict(seq_patterns.most_common(15)),
        "solid_sequence_patterns": dict(solid_seq_patterns.most_common(15)),
        "family_feature_breakdown": {fam: dict(c.most_common()) for fam, c in family_feats.items()},
        "family_mean_param_coverage": family_mean_cov,
        "operation_vocabulary": sorted(feature_freq.keys()),
        "reconstruction_coverage": {
            "flange_vocab": sorted(FLANGE_VOCAB),
            "parts_buildable_flange_vocab": flange_buildable,
            "pct_buildable_flange_vocab": round(100 * flange_buildable / max(n, 1), 1),
            "extended_vocab": sorted(EXTENDED_VOCAB),
            "parts_buildable_extended_vocab": extended_buildable,
            "pct_buildable_extended_vocab": round(100 * extended_buildable / max(n, 1), 1),
        },
    }


def main() -> dict[str, Any]:
    pairs = _load_pairs()
    stats = compute_stats(pairs)
    out = TRAINING_DIR / "feature_graph_stats.json"
    out.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"wrote {out}  ({stats['n_parts']} parts)")
    return stats


if __name__ == "__main__":
    s = main()
    print(json.dumps({
        "feature_frequency": s["feature_frequency"],
        "family_frequency": s["family_frequency"],
        "geometry_frequency": s["geometry_frequency"],
        "average_features_per_part": s["average_features_per_part"],
        "average_graph_depth": s["average_graph_depth"],
        "reconstruction_coverage": s["reconstruction_coverage"],
        "operation_vocabulary": s["operation_vocabulary"],
    }, indent=2))
