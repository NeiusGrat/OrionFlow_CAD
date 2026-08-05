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
                 near:<x>,<y>,<z>    the ONE edge whose midpoint is closest
  dict form:     {"z": <height mm>}  edges lying in the horizontal plane at z

``near`` is the odd one out and exists for a specific reason. Every other form
names a *class* of edges — all the vertical ones, all the rims of radius 5 —
which is right for an authored design where the intent is "break every corner".
It is useless for a person who clicked one edge and asked to chamfer *that*.

Naming that edge by its OCC index would not survive a rebuild: change an
unrelated dimension and Edge12 can become a different edge. A point does
survive, because it is a statement about geometry rather than about
FreeCAD's numbering — the edge nearest (x, y, z) after the rebuild is the same
edge a person would point at, right up until the edit moves it far enough that
it genuinely is not, at which point the resolution fails visibly rather than
silently chamfering something else.
"""

KEYWORDS = {"all", "top", "bottom", "vertical", "horizontal", "circular",
            "straight", "convex", "concave"}
AXES = ("x", "y", "z")

#: How far a ``near`` point may sit from an edge midpoint, in mm, before the
#: selector is treated as matching nothing. Generous enough to survive a
#: parameter nudge, tight enough that a deleted edge does not silently hand the
#: operation to its neighbour.
NEAR_TOLERANCE_MM = 2.0

HELP = ('one of "all" | "top" | "bottom" | "vertical" | "horizontal" | '
        '"circular" | "straight" | "convex" | "concave" | "direction:<x|y|z>" | '
        '"radius:<mm>" (circular edges of that radius) | "largest:<n>" '
        '(the n longest edges) | "near:<x>,<y>,<z>" (the single edge closest '
        'to that point) | {"z": <height mm>}')


def parse(selector):
    """Normalize a selector into ``(kind, arg)``; ``None`` if invalid.

    Kinds: the keywords (arg None), "direction" (arg "x"/"y"/"z"),
    "radius" (arg float > 0), "largest" (arg int >= 1), "z" (arg float),
    "near" (arg ``(x, y, z)``).
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
        if kind == "near":
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) != 3:
                return None
            try:
                point = tuple(float(p) for p in parts)
            except ValueError:
                return None
            if any(p != p for p in point):  # NaN
                return None
            return (kind, point)
    return None
