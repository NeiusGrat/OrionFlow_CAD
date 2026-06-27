"""OrionFlow DSL — a deterministic, lossless text serialization of FeatureGraph.

This is NOT a new language: it is a readable surface syntax *over* the existing
FeatureGraph IR, so OrionFlow keeps one canonical representation with two skins
(JSON for machines, DSL for humans/LLMs). The contract is a byte-stable round
trip ``from_dsl(to_dsl(graph)) == graph`` for the reconstructable content, which
``__main__`` self-checks.

Grammar (line-oriented; payloads are compact JSON values so the round trip is
exact and whitespace-insensitive in values):

    # OrionFlow DSL v1
    DOC   name=... label=... object_count=...
    PARAM name=... value=... unit=... bound_to=[...]
    FEAT  id=... type=... type_id=... label=... parameters={...}
    SKETCH id=... plane=... placement={...} ...
      GEOM    index=... type=... ...
      EXTGEOM type=... source_object=... ...
      CON     index=... type=... first=... value=...
    ENDSKETCH
    DEP   source=... target=... kind=...
    EXPR  object=... property=... expression=... referenced_objects=[...]

Standalone (no FreeCAD, no heavy deps). Use ``compile`` direction:
    .FCStd -> extractor -> FeatureGraph -> to_dsl  (and from_dsl -> FeatureGraph -> reconstruct).
"""

from __future__ import annotations

import json
import re
from typing import Any

HEADER = "# OrionFlow DSL v1"
_SPLIT_RE = re.compile(r" (?=[A-Za-z_]\w*=)")  # split before ` key=`, spaces-in-values safe


def _emit(d: dict[str, Any]) -> str:
    return " ".join(
        "%s=%s" % (k, json.dumps(v, separators=(",", ":"), ensure_ascii=False))
        for k, v in d.items()
    )


def _parse_kv(s: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    s = s.strip()
    if not s:
        return out
    for part in _SPLIT_RE.split(s):
        if "=" not in part:
            continue
        k, raw = part.split("=", 1)
        try:
            out[k] = json.loads(raw)
        except Exception:
            out[k] = raw
    return out


# ---------------------------------------------------------------------------
# FeatureGraph -> DSL
# ---------------------------------------------------------------------------

def to_dsl(graph: dict[str, Any]) -> str:
    lines = [HEADER]
    doc = dict(graph.get("document", {}))
    lines.append("DOC " + _emit(doc))
    for p in graph.get("parameters", []):
        lines.append("PARAM " + _emit(p))
    for f in graph.get("features", []):
        lines.append("FEAT " + _emit(f))
    for s in graph.get("sketches", []):
        head = {k: v for k, v in s.items()
                if k not in ("geometry", "external_geometry", "constraints")}
        lines.append("SKETCH " + _emit(head))
        for g in s.get("geometry", []):
            lines.append("  GEOM " + _emit(g))
        for g in s.get("external_geometry", []):
            lines.append("  EXTGEOM " + _emit(g))
        for c in s.get("constraints", []):
            lines.append("  CON " + _emit(c))
        lines.append("ENDSKETCH")
    for d in graph.get("dependencies", []):
        lines.append("DEP " + _emit(d))
    for e in graph.get("expressions", []):
        lines.append("EXPR " + _emit(e))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# DSL -> FeatureGraph
# ---------------------------------------------------------------------------

def from_dsl(text: str) -> dict[str, Any]:
    graph: dict[str, Any] = {
        "schema_version": "ofl_fcstd_v1",
        "document": {}, "features": [], "sketches": [],
        "dependencies": [], "parameters": [], "constraints": [], "expressions": [],
    }
    cur_sketch: dict[str, Any] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tag, _, rest = stripped.partition(" ")
        if tag == "DOC":
            graph["document"] = _parse_kv(rest)
        elif tag == "PARAM":
            graph["parameters"].append(_parse_kv(rest))
        elif tag == "FEAT":
            graph["features"].append(_parse_kv(rest))
        elif tag == "SKETCH":
            cur_sketch = _parse_kv(rest)
            cur_sketch.setdefault("geometry", [])
            cur_sketch.setdefault("external_geometry", [])
            cur_sketch.setdefault("constraints", [])
            graph["sketches"].append(cur_sketch)
        elif tag == "GEOM" and cur_sketch is not None:
            cur_sketch["geometry"].append(_parse_kv(rest))
        elif tag == "EXTGEOM" and cur_sketch is not None:
            cur_sketch["external_geometry"].append(_parse_kv(rest))
        elif tag == "CON" and cur_sketch is not None:
            cur_sketch["constraints"].append(_parse_kv(rest))
        elif tag == "ENDSKETCH":
            cur_sketch = None
        elif tag == "DEP":
            graph["dependencies"].append(_parse_kv(rest))
        elif tag == "EXPR":
            graph["expressions"].append(_parse_kv(rest))
    return graph


def _roundtrip_equal(graph: dict[str, Any]) -> bool:
    """True if DSL round-trips the reconstructable content exactly."""
    back = from_dsl(to_dsl(graph))
    keys = ("document", "features", "sketches", "dependencies", "parameters", "expressions")
    return all(back.get(k) == graph.get(k) for k in keys)


if __name__ == "__main__":
    import sys

    src = json.load(open(sys.argv[1], encoding="utf-8"))
    g = src.get("feature_graph", src)
    g.pop("multimodal", None)
    text = to_dsl(g)
    ok = _roundtrip_equal(g)
    sys.stdout.write(text)
    sys.stdout.write("\n# roundtrip_exact=%s\n" % ok)
