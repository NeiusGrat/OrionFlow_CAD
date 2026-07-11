"""Edge-selector grammar — the shared language for naming edges semantically.

Single source of truth for the selector vocabulary used by Fillet/Chamfer
``parameters._Edges`` in the FeatureGraph. The harness validates authored
selectors against this grammar (orion_agent/harness/featuregraph.py) and the
compiler resolves them against real topology (freecad/reconstruct.py), so the
two sides can never drift.

Pure stdlib, NO FreeCAD imports — geometric resolution stays in reconstruct.py.
Both consumers load this file by absolute path (module name
``_orion_repo_edge_selectors``) because FreeCAD ships its own lowercase
``freecad`` package that would shadow a normal import.

Grammar:
  keywords:      all | top | bottom | vertical | horizontal | circular |
                 straight | convex | concave
  parameterized: direction:<x|y|z>   straight edges parallel to that axis
                 radius:<mm>         circular edges of that radius (hole rims)
                 largest:<n>         the n longest edges
  dict form:     {"z": <height mm>}  edges lying in the horizontal plane at z
"""

KEYWORDS = {"all", "top", "bottom", "vertical", "horizontal", "circular",
            "straight", "convex", "concave"}
AXES = ("x", "y", "z")

HELP = ('one of "all" | "top" | "bottom" | "vertical" | "horizontal" | '
        '"circular" | "straight" | "convex" | "concave" | "direction:<x|y|z>" | '
        '"radius:<mm>" (circular edges of that radius) | "largest:<n>" '
        '(the n longest edges) | {"z": <height mm>}')


def parse(selector):
    """Normalize a selector into ``(kind, arg)``; ``None`` if invalid.

    Kinds: the keywords (arg None), "direction" (arg "x"/"y"/"z"),
    "radius" (arg float > 0), "largest" (arg int >= 1), "z" (arg float).
    Case-insensitive; surrounding whitespace ignored.
    """
    if isinstance(selector, dict):
        z = selector.get("z")
        if isinstance(z, (int, float)) and not isinstance(z, bool):
            return ("z", float(z))
        return None
    if not isinstance(selector, str):
        return None
    s = selector.strip().lower()
    if s in KEYWORDS:
        return (s, None)
    if ":" in s:
        kind, _, raw = s.partition(":")
        kind, raw = kind.strip(), raw.strip()
        if kind == "direction":
            return (kind, raw) if raw in AXES else None
        if kind == "radius":
            try:
                value = float(raw)
            except ValueError:
                return None
            return (kind, value) if value > 0 else None
        if kind == "largest":
            try:
                n = int(raw)
            except ValueError:
                return None
            return (kind, n) if n >= 1 else None
    return None
