"""Recover the named-parameter -> geometry binding (the editability map).

This dataset has *no* sketch constraints or expressions, so the parametric link
that the gNucleus benchmark scores is reconstructed deterministically by matching
each named ``key_parameter`` value against the actual numeric measurements in the
FeatureGraph (circle diameters/radii, pad/pocket lengths, bolt-circle distances,
circle counts). Keyword hints in the parameter name disambiguate equal values.
"""

from __future__ import annotations

import re
from typing import Any

from .feature_graph import iter_measurements

# name keyword -> preferred measurement kinds, in priority order
_KEYWORD_KINDS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("bolt_circle", "boltcircle", "pcd", "pitch_circle", "bcd"), ("bolt_circle_diameter",)),
    (("number", "num_", "count", "qty", "n_holes", "holes", "teeth", "n_"), ("count",)),
    (("diameter", "dia", "bore", "od", "id_"), ("diameter",)),
    (("radius", "fillet", "round"), ("radius",)),
    (("thickness", "height", "depth", "length", "len", "extrude", "tall", "long"), ("length",)),
    (("width", "size", "across"), ("diameter", "length")),
]

_LINE_RE = re.compile(r"^\s*[-*]?\s*([A-Za-z0-9_]+)\s*[:=]\s*([-+]?\d*\.?\d+)\s*([A-Za-z°]*)")


def parse_key_parameters(text: str) -> list[dict[str, Any]]:
    """Parse the markdown ``key_parameters`` string into typed entries.

    Each entry: {name, value (int if integral & unitless else float), unit}.
    """
    params: list[dict[str, Any]] = []
    if not text:
        return params
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        name, raw, unit = m.group(1), m.group(2), m.group(3)
        unit = unit.strip() or None
        val: float | int = float(raw)
        # integral & unitless -> treat as a count
        if unit is None and float(raw) == int(float(raw)):
            val = int(float(raw))
        params.append({"name": name, "value": val, "unit": unit})
    return params


def _preferred_kinds(name: str) -> tuple[str, ...]:
    low = name.lower()
    for keywords, kinds in _KEYWORD_KINDS:
        if any(k in low for k in keywords):
            return kinds
    return ()


def _close(a: float, b: float) -> bool:
    # 0.5% relative (or 0.05mm floor) absorbs nominal-vs-modeled rounding such as
    # a gear's stated outer_diameter vs its actual tooth-tip span.
    return abs(a - b) <= max(0.05, 5e-3 * max(abs(a), abs(b)))


def map_parameters(graph: dict[str, Any], key_parameters_text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (parameters_with_bindings, stats).

    ``parameters`` is the list to drop into ``graph['parameters']``. Each carries
    a ``bound_to`` list (possibly empty when no geometry matches the value).
    """
    parsed = parse_key_parameters(key_parameters_text)
    measurements = iter_measurements(graph)
    out: list[dict[str, Any]] = []
    n_bound = 0

    for p in parsed:
        name, value = p["name"], float(p["value"])
        pref = _preferred_kinds(name)

        # 1) preferred-kind matches (may be several, e.g. all bolt holes)
        cands = [m for m in measurements if m["kind"] in pref and _close(m["value"], value)]

        # 2) fallback: closest match across any kind
        if not cands:
            any_close = [m for m in measurements if _close(m["value"], value)]
            if any_close:
                best = min(any_close, key=lambda m: abs(m["value"] - value))
                cands = [best]

        bound_to = _dedupe([
            {"target": m["target"], "property": m["property"], "relation": m["relation"]}
            for m in cands
        ])
        if bound_to:
            n_bound += 1
        out.append({
            "name": name,
            "value": p["value"],
            "unit": p["unit"],
            "bound_to": bound_to,
        })

    stats = {
        "n_params": len(parsed),
        "n_bound": n_bound,
        "n_unbound": len(parsed) - n_bound,
        "coverage": round(n_bound / len(parsed), 4) if parsed else 0.0,
        "unbound_names": [p["name"] for p, o in zip(parsed, out) if not o["bound_to"]],
    }
    return out, stats


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, res = set(), []
    for it in items:
        key = (it["target"], it["property"])
        if key not in seen:
            seen.add(key)
            res.append(it)
    return res
