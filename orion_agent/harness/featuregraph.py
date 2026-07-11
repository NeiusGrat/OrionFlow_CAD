"""Harness-side FeatureGraph authoring support.

The FeatureGraph is the canonical IR between the model and FreeCAD: the LLM
emits a *compact authoring form* (features + sketches + dependencies), this
module normalizes it into the full canonical schema
(``freecad/feature_graph_schema.json``), validates it structurally and with
engineering checks, and the addon compiles the result into a native PartDesign
feature tree via ``freecad/reconstruct.py``. The LLM never creates geometry —
it only ever describes features.

Deterministic, stdlib-only (jsonschema is an optional backstop).
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Optional

SCHEMA_VERSION = "ofl_fcstd_v1"

# Vocabulary the deterministic compiler (freecad/reconstruct.py) can build.
SUPPORTED_FEATURES = {"Body", "Sketch", "Pad", "Pocket", "Revolution", "Groove",
                      "Hole", "Thickness", "LinearPattern", "PolarPattern",
                      "Fillet", "Chamfer", "Loft", "Sweep", "Mirrored", "Draft"}
PROFILE_OPS = {"Pad", "Pocket", "Revolution", "Groove", "Hole", "Loft", "Sweep"}
TRANSFORM_OPS = {"LinearPattern", "PolarPattern", "Mirrored"}
DRESSUP_OPS = {"Fillet", "Chamfer"}
ADDITIVE_OPS = {"Pad", "Revolution"}        # Loft/Sweep too, unless Subtractive
GEOM_TYPES = {"Circle", "LineSegment", "ArcOfCircle", "BSpline", "Bezier"}
PLANES = {"XY", "XZ", "YZ"}
AXIS_ROLES = {"X_Axis", "Y_Axis", "Z_Axis"}
MIRROR_PLANES = {"XY_Plane", "XZ_Plane", "YZ_Plane"}
FACE_SELECTORS = {"all", "vertical", "horizontal", "top", "bottom"}
# Keyword selectors; the full grammar (incl. direction:/radius:/largest: and
# {"z": mm}) lives in freecad/edge_selectors.py, shared with the compiler.
EDGE_SELECTORS = {"all", "top", "bottom", "vertical", "horizontal", "circular",
                  "straight", "convex", "concave"}


def _edge_selector_grammar():
    """Load freecad/edge_selectors.py by absolute path (module name
    ``_orion_repo_edge_selectors``) — the single source of truth for the
    selector grammar. A path load, not a normal import, because FreeCAD ships
    its own lowercase ``freecad`` package that would shadow the repo's."""
    import importlib.util
    import sys

    name = "_orion_repo_edge_selectors"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    from orion_agent.shared.config import get_config
    path = os.path.join(get_config().repo_root, "freecad", "edge_selectors.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod

_TYPE_ID = {
    "Body": "PartDesign::Body",
    "Sketch": "Sketcher::SketchObject",
    "Pad": "PartDesign::Pad",
    "Pocket": "PartDesign::Pocket",
    "Revolution": "PartDesign::Revolution",
    "Groove": "PartDesign::Groove",
    "Hole": "PartDesign::Hole",
    "Thickness": "PartDesign::Thickness",
    "LinearPattern": "PartDesign::LinearPattern",
    "PolarPattern": "PartDesign::PolarPattern",
    "Mirrored": "PartDesign::Mirrored",
    "Fillet": "PartDesign::Fillet",
    "Chamfer": "PartDesign::Chamfer",
    "Draft": "PartDesign::Draft",
    "Loft": "PartDesign::AdditiveLoft",
    "Sweep": "PartDesign::AdditivePipe",
}

# The authoring guide doubles as the tool description the model sees.
AUTHORING_GUIDE = (
    "Feature vocabulary: Sketch (on plane XY/XZ/YZ), Pad, Pocket, Revolution, "
    "Groove, Hole, Loft, Sweep, LinearPattern, PolarPattern, Mirrored, Draft. "
    "Sketch geometry: "
    '{"type":"Circle","cx":..,"cy":..,"radius":..}, '
    '{"type":"LineSegment","sx":..,"sy":..,"ex":..,"ey":..}, '
    '{"type":"ArcOfCircle","cx":..,"cy":..,"radius":..,"first":<rad>,"last":<rad>}. '
    "Line/arc profiles MUST close into a loop. Units are mm. Features build in "
    "list order; a sketch listed after a solid feature is placed automatically "
    "on top of the current solid, so 'Pad the base, then Pocket a circle' cuts "
    'from the top face; a sketch may instead set "z": <mm> for an explicit '
    "height. Pad/Pocket need parameters.Length (>0). Revolution/"
    'Groove need parameters.Angle and parameters._ReferenceAxis {"role":'
    '"X_Axis"|"Y_Axis"|"Z_Axis"}. Loft (its profile sketch is the bottom '
    'section) needs parameters._Sections ["<sketch_id>",..] — section sketches '
    'each with their own "z". Sweep runs its profile along parameters._Spine '
    '"<sketch_id>", an OPEN path sketch on a perpendicular plane (e.g. profile '
    "on XY at the path start, spine on XZ); Loft/Sweep add material unless "
    "parameters.Subtractive is true. Patterns need parameters.Occurrences plus "
    'Length+_Direction{"role":..} (Linear) or Angle+_Axis{"role":..} (Polar). '
    'Mirrored mirrors the previous feature across parameters._Plane {"role":'
    '"XY_Plane"|"XZ_Plane"|"YZ_Plane"}. Draft tapers faces for molding: '
    'parameters.Angle (degrees, >0) plus parameters._Faces "vertical" (default)'
    '|"all"|"top"|"bottom"|"horizontal"; the neutral plane defaults to the '
    "bottom face. "
    "Fillet needs parameters.Radius and Chamfer needs parameters.Size, plus "
    'parameters._Edges selecting edges semantically: "all", "top", "bottom", '
    '"vertical", "horizontal", "circular", "straight", "convex", "concave", '
    '"direction:<x|y|z>", "radius:<mm>" (circular edges of that radius, e.g. '
    'hole rims), "largest:<n>" (the n longest edges), or {"z": <height mm>}; '
    "they round/bevel the previous solid "
    'feature (or set parameters._Base {"object": "<feature_id>"}). '
    "Link each profile feature to its sketch via dependencies "
    '[{"source":"<sketch_id>","target":"<feature_id>","kind":"profile"}]. '
    "Example — 80x50x10 plate with a 10mm centre hole:\n"
    '{"features":[{"id":"sk_base","type":"Sketch"},'
    '{"id":"pad_base","type":"Pad","parameters":{"Length":10}},'
    '{"id":"sk_hole","type":"Sketch"},'
    '{"id":"cut_hole","type":"Pocket","parameters":{"Length":10}}],'
    '"sketches":[{"id":"sk_base","plane":"XY","geometry":['
    '{"type":"LineSegment","sx":-40,"sy":-25,"ex":40,"ey":-25},'
    '{"type":"LineSegment","sx":40,"sy":-25,"ex":40,"ey":25},'
    '{"type":"LineSegment","sx":40,"sy":25,"ex":-40,"ey":25},'
    '{"type":"LineSegment","sx":-40,"sy":25,"ex":-40,"ey":-25}]},'
    '{"id":"sk_hole","plane":"XY","geometry":['
    '{"type":"Circle","cx":0,"cy":0,"radius":5}]}],'
    '"dependencies":[{"source":"sk_base","target":"pad_base","kind":"profile"},'
    '{"source":"sk_hole","target":"cut_hole","kind":"profile"}]}'
)


# --------------------------------------------------------------------------- #
# Normalization: compact authoring form -> canonical schema
# --------------------------------------------------------------------------- #


def normalize(graph: dict) -> tuple[dict, list[str]]:
    """Canonicalize a compact authoring graph; returns (canonical, notes).

    Fills schema-required boilerplate (type_id, label, geometry indices,
    document block), inserts Sketch feature entries the model left out, and
    infers missing profile dependencies from feature order. Every non-obvious
    repair is reported in ``notes`` so the observation stays transparent.
    """
    notes: list[str] = []
    g: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_id": str(graph.get("source_id", "orion_agent")),
        "document": {"name": "OrionFlow", "label": "OrionFlow", "object_count": 0},
        "features": [],
        "sketches": [],
        "dependencies": [],
        "parameters": [],
        "constraints": [],
        "expressions": [],
    }
    for sec in ("parameters", "constraints", "expressions"):
        if isinstance(graph.get(sec), list):
            g[sec] = graph[sec]

    # ---- sketches ------------------------------------------------------- #
    for sk in graph.get("sketches", []) or []:
        if not isinstance(sk, dict):
            continue
        geometry = []
        for i, item in enumerate(sk.get("geometry", []) or []):
            it = dict(item) if isinstance(item, dict) else {}
            it.setdefault("index", i)
            it.setdefault("construction", False)
            geometry.append(it)
        entry: dict[str, Any] = {
            "id": str(sk.get("id", "")),
            "plane": sk.get("plane", "XY"),
            "geometry": geometry,
            "constraints": sk.get("constraints", []) or [],
        }
        if isinstance(sk.get("z"), (int, float)) and not isinstance(sk.get("z"), bool):
            entry["z"] = float(sk["z"])       # explicit height (loft sections)
        if isinstance(sk.get("global_placement"), dict):
            entry["global_placement"] = sk["global_placement"]
        if isinstance(sk.get("external_geometry"), list):
            entry["external_geometry"] = sk["external_geometry"]
        g["sketches"].append(entry)
    sketch_ids = [sk["id"] for sk in g["sketches"]]

    # ---- dependencies (explicit ones pass through) ----------------------- #
    deps: list[dict] = []
    for d in graph.get("dependencies", []) or []:
        if isinstance(d, dict) and d.get("source") and d.get("target"):
            deps.append({"source": str(d["source"]), "target": str(d["target"]),
                         "kind": d.get("kind", "profile")})
    profile_of = {d["target"]: d["source"] for d in deps if d["kind"] == "profile"}

    # ---- features: walk in order, inserting missing Sketch entries ------- #
    emitted: set[str] = set()
    unconsumed: list[str] = []          # sketches emitted but not yet used as a profile

    def emit_sketch(sid: str) -> None:
        if sid in emitted:
            return
        g["features"].append({"id": sid, "type": "Sketch",
                              "type_id": _TYPE_ID["Sketch"], "label": sid,
                              "parameters": {}})
        emitted.add(sid)
        unconsumed.append(sid)

    for f in graph.get("features", []) or []:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id", ""))
        ftype = str(f.get("type", ""))
        if ftype == "Sketch":
            emit_sketch(fid)
            continue

        params = dict(f.get("parameters", {}) or {})
        # Loft sections / Sweep spine consume their sketches BEFORE profile
        # inference, so a section is never mistaken for the profile.
        if ftype == "Loft":
            for sid in params.get("_Sections") or []:
                sid = str(sid)
                emit_sketch(sid)
                if sid in unconsumed:
                    unconsumed.remove(sid)
        if ftype == "Sweep" and params.get("_Spine"):
            sid = str(params["_Spine"])
            emit_sketch(sid)
            if sid in unconsumed:
                unconsumed.remove(sid)
        if ftype in PROFILE_OPS:
            src = profile_of.get(fid)
            if src is None:
                # Infer: the nearest yet-unconsumed sketch, else the next
                # sketch defined but never listed as a feature.
                candidates = unconsumed or [s for s in sketch_ids if s not in emitted]
                if candidates:
                    src = candidates[-1] if unconsumed else candidates[0]
                    profile_of[fid] = src
                    deps.append({"source": src, "target": fid, "kind": "profile"})
                    notes.append(f"inferred profile {src} -> {fid}")
            if src is not None:
                emit_sketch(src)
                if src in unconsumed:
                    unconsumed.remove(src)
            if ftype in ("Revolution", "Groove") and "Angle" not in params:
                params["Angle"] = 360.0
                notes.append(f"{fid}: defaulted Angle to 360")
        if ftype in TRANSFORM_OPS:
            if ftype == "PolarPattern":
                params.setdefault("Angle", 360.0)
                if "_Axis" not in params:
                    params["_Axis"] = {"role": "Z_Axis"}
                    notes.append(f"{fid}: defaulted pattern axis to Z_Axis")
            elif ftype == "LinearPattern":
                if "_Direction" not in params:
                    params["_Direction"] = {"role": "X_Axis"}
                    notes.append(f"{fid}: defaulted pattern direction to X_Axis")
            else:  # Mirrored: normalize plane aliases, default YZ_Plane
                ref = params.get("_Plane")
                role = str(ref.get("role", "")) if isinstance(ref, dict) else ""
                if role in PLANES:
                    role += "_Plane"
                if role not in MIRROR_PLANES:
                    role = "YZ_Plane"
                    notes.append(f"{fid}: defaulted mirror plane to YZ_Plane")
                params["_Plane"] = {"role": role}
        # Origin-axis references pass an empty sub-element, not a sketch axis.
        for ref_key in ("_ReferenceAxis", "_Direction", "_Axis", "_Plane"):
            ref = params.get(ref_key)
            if isinstance(ref, dict) and ref.get("role") and "subs" not in ref:
                ref["subs"] = [""]

        g["features"].append({
            "id": fid, "type": ftype,
            "type_id": f.get("type_id") or _TYPE_ID.get(ftype, ftype),
            "label": f.get("label") or fid,
            "parameters": params,
        })
        emitted.add(fid)

    # Sketches never referenced anywhere still compile (as bare sketches).
    for sid in sketch_ids:
        if sid not in emitted:
            emit_sketch(sid)
            notes.append(f"sketch {sid} was not in features; appended")

    g["dependencies"] = deps
    g["document"]["object_count"] = len(g["features"])
    return g, notes


# --------------------------------------------------------------------------- #
# Validation: structural + engineering checks
# --------------------------------------------------------------------------- #


def validate(graph: dict) -> list[str]:
    """Return actionable error strings (empty == compilable)."""
    errors: list[str] = []
    features = graph.get("features", [])
    sketches = {sk.get("id"): sk for sk in graph.get("sketches", [])}
    feature_ids = [f.get("id") for f in features]

    if not features:
        return ["graph has no features"]
    dupes = {i for i in feature_ids if feature_ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate feature ids: {sorted(dupes)}")

    profile_of = {d.get("target"): d.get("source")
                  for d in graph.get("dependencies", [])
                  if d.get("kind") == "profile"}

    # Sweep spine sketches are open paths; exempt them from profile closure.
    spine_ids = {str((f.get("parameters") or {}).get("_Spine"))
                 for f in features if f.get("type") == "Sweep"
                 and (f.get("parameters") or {}).get("_Spine")}

    solid_count = 0
    seen_buildable = False              # a solid exists for dressups to act on
    for f in features:
        fid, ftype = f.get("id", "?"), f.get("type", "?")
        params = f.get("parameters", {}) or {}
        if ftype not in SUPPORTED_FEATURES:
            errors.append(
                f"{fid}: unsupported feature type '{ftype}' — the compiler "
                f"supports {sorted(SUPPORTED_FEATURES - {'Body'})}; use "
                "write_code for anything else"
            )
            continue
        if ftype == "Sketch":
            sk = sketches.get(fid)
            if sk is None:
                errors.append(f"{fid}: Sketch feature has no entry in 'sketches'")
            else:
                errors.extend(_check_sketch(sk, allow_open=fid in spine_ids))
            continue
        additive = (ftype in ADDITIVE_OPS
                    or (ftype in ("Loft", "Sweep") and not params.get("Subtractive")))
        if additive:
            solid_count += 1          # additive ops create material
        if ftype in PROFILE_OPS:
            src = profile_of.get(fid)
            if src is None:
                errors.append(
                    f"{fid}: {ftype} has no profile sketch — add a dependency "
                    f'{{"source": "<sketch_id>", "target": "{fid}", "kind": "profile"}}'
                )
            elif src not in sketches:
                errors.append(f"{fid}: profile sketch '{src}' does not exist")
            elif not any(not g.get("construction") for g in sketches[src].get("geometry", [])):
                errors.append(f"{fid}: profile sketch '{src}' has no non-construction geometry")
        if ftype in ("Pad", "Pocket"):
            length = params.get("Length")
            if not isinstance(length, (int, float)) or length <= 0:
                errors.append(f"{fid}: {ftype} needs parameters.Length > 0 (got {length!r})")
        if ftype in ("Revolution", "Groove"):
            ax = params.get("_ReferenceAxis")
            if not (isinstance(ax, dict) and (ax.get("role") in AXIS_ROLES or ax.get("object"))):
                errors.append(
                    f"{fid}: {ftype} needs parameters._ReferenceAxis "
                    '{"role": "X_Axis"|"Y_Axis"|"Z_Axis"}'
                )
        if ftype == "Hole":
            dia = params.get("Diameter")
            if dia is not None and (not isinstance(dia, (int, float)) or dia <= 0):
                errors.append(f"{fid}: Hole Diameter must be > 0 (got {dia!r})")
        if ftype == "Loft":
            secs = params.get("_Sections")
            if not isinstance(secs, list) or not secs:
                errors.append(
                    f'{fid}: Loft needs parameters._Sections ["<sketch_id>", ...] '
                    '— section sketches at their own "z" heights'
                )
            else:
                for s in secs:
                    if str(s) not in sketches:
                        errors.append(f"{fid}: Loft section sketch '{s}' does not exist")
                    elif str(s) == profile_of.get(fid):
                        errors.append(f"{fid}: Loft section '{s}' is also its profile")
        if ftype == "Sweep":
            spine = params.get("_Spine")
            if not spine or str(spine) not in sketches:
                errors.append(
                    f'{fid}: Sweep needs parameters._Spine "<sketch_id>" — an open '
                    "path sketch on a perpendicular plane (e.g. XZ)"
                )
            elif str(spine) == profile_of.get(fid):
                errors.append(f"{fid}: Sweep spine '{spine}' is also its profile")
        if ftype in ("LinearPattern", "PolarPattern"):
            occ = params.get("Occurrences")
            if not isinstance(occ, (int, float)) or occ < 2:
                errors.append(f"{fid}: {ftype} needs parameters.Occurrences >= 2")
        if ftype == "Mirrored":
            role = (params.get("_Plane") or {}).get("role")
            if role not in MIRROR_PLANES:
                errors.append(
                    f'{fid}: Mirrored needs parameters._Plane {{"role": '
                    f'"XY_Plane"|"XZ_Plane"|"YZ_Plane"}} (got {role!r})'
                )
        if ftype == "Draft":
            if not seen_buildable:
                errors.append(f"{fid}: Draft must come after a solid feature")
            angle = params.get("Angle")
            if not isinstance(angle, (int, float)) or angle <= 0:
                errors.append(f"{fid}: Draft needs parameters.Angle > 0 degrees (got {angle!r})")
            if not (params.get("_Base") or {}).get("faces"):
                fsel = params.get("_Faces", "vertical")
                if fsel not in FACE_SELECTORS:
                    errors.append(
                        f"{fid}: Draft parameters._Faces must be one of "
                        f"{sorted(FACE_SELECTORS)}"
                    )
        if ftype in DRESSUP_OPS:
            if not seen_buildable:
                errors.append(f"{fid}: {ftype} must come after a solid feature")
            size_key = "Radius" if ftype == "Fillet" else "Size"
            size = params.get(size_key)
            if not isinstance(size, (int, float)) or size <= 0:
                errors.append(f"{fid}: {ftype} needs parameters.{size_key} > 0 (got {size!r})")
            base = params.get("_Base") or {}
            if not base.get("edges"):
                sel = params.get("_Edges")
                try:
                    grammar = _edge_selector_grammar()
                    valid_sel = grammar.parse(sel) is not None
                    sel_help = grammar.HELP
                except Exception:  # noqa: BLE001 - grammar file missing: legacy check
                    valid_sel = (sel in EDGE_SELECTORS
                                 or (isinstance(sel, dict)
                                     and isinstance(sel.get("z"), (int, float))))
                    sel_help = f'one of {sorted(EDGE_SELECTORS)} or {{"z": <height mm>}}'
                if not valid_sel:
                    errors.append(
                        f"{fid}: {ftype} needs parameters._Edges — {sel_help}"
                    )
        if additive:
            seen_buildable = True       # material now exists for dressups
    if solid_count == 0:
        errors.append("graph produces no solid: add at least one "
                      "Pad/Revolution/Loft/Sweep")

    errors.extend(_jsonschema_backstop(graph))
    return errors


def _check_sketch(sk: dict, allow_open: bool = False) -> list[str]:
    """Per-sketch geometry checks, including profile closure.

    ``allow_open`` (Sweep spines): the path may be an open chain, but must
    still be a single connected one.
    """
    errors: list[str] = []
    sid = sk.get("id", "?")
    if sk.get("plane") not in PLANES and not sk.get("global_placement"):
        errors.append(f"{sid}: plane must be one of {sorted(PLANES)}")

    endpoints: list[tuple[float, float]] = []
    for geo in sk.get("geometry", []):
        gtype = geo.get("type")
        if gtype not in GEOM_TYPES:
            errors.append(f"{sid}: unsupported geometry type {gtype!r} (use {sorted(GEOM_TYPES)})")
            continue
        try:
            if gtype == "Circle":
                if float(geo["radius"]) <= 0:
                    errors.append(f"{sid}: Circle radius must be > 0")
                float(geo["cx"]), float(geo["cy"])
            elif gtype == "LineSegment":
                a = (float(geo["sx"]), float(geo["sy"]))
                b = (float(geo["ex"]), float(geo["ey"]))
                if not geo.get("construction"):
                    endpoints.extend([a, b])
            elif gtype == "ArcOfCircle":
                r = float(geo["radius"])
                if r <= 0:
                    errors.append(f"{sid}: Arc radius must be > 0")
                cx, cy = float(geo["cx"]), float(geo["cy"])
                for ang_key in ("first", "last"):
                    ang = float(geo[ang_key])
                    if not geo.get("construction"):
                        endpoints.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{sid}: {gtype} is missing/has bad fields ({exc})")

    # Closure: every line/arc endpoint must meet exactly one partner endpoint.
    # Matching rounds to 1e-4 mm so truncated constants (e.g. pi to 7 digits
    # in arc angles) never produce false "open profile" failures.
    if endpoints:
        counts: dict[tuple[float, float], int] = {}
        for x, y in endpoints:
            key = (round(x, 4), round(y, 4))
            counts[key] = counts.get(key, 0) + 1
        dangling = [k for k, n in counts.items() if n % 2 == 1]
        if allow_open:
            if len(dangling) > 2:
                errors.append(
                    f"{sid}: path must be one connected chain — found "
                    f"{len(dangling)} loose endpoint(s) at {dangling[:4]}"
                )
        elif dangling:
            errors.append(
                f"{sid}: profile is not closed — dangling endpoint(s) at "
                f"{dangling[:3]}; every line/arc endpoint must coincide with "
                "exactly one other endpoint"
            )
    return errors


def _jsonschema_backstop(graph: dict) -> list[str]:
    """Validate against the canonical schema file when jsonschema is available."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []
    try:
        from orion_agent.shared.config import get_config
        schema_path = os.path.join(get_config().repo_root, "freecad",
                                   "feature_graph_schema.json")
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except Exception:  # noqa: BLE001 - schema file is optional at runtime
        return []
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(graph), key=lambda e: list(e.path))
    ][:6]


# --------------------------------------------------------------------------- #
# Summaries (token-bounded observations)
# --------------------------------------------------------------------------- #


def summarize_graph(graph: dict, max_features: int = 20) -> str:
    """Compact, human/model-readable view of a FeatureGraph."""
    features = graph.get("features", [])
    sketches = {sk.get("id"): sk for sk in graph.get("sketches", [])}
    profile_of = {d.get("target"): d.get("source")
                  for d in graph.get("dependencies", [])
                  if d.get("kind") == "profile"}
    if not features:
        return "empty FeatureGraph (no features)"

    lines = [f"FeatureGraph: {len(features)} feature(s)"]
    shown = 0
    for f in features:
        if shown >= max_features:
            lines.append(f"... and {len(features) - shown} more")
            break
        fid, ftype = f.get("id", "?"), f.get("type", "?")
        if ftype == "Body":
            continue
        if ftype == "Sketch":
            sk = sketches.get(fid, {})
            geo = sk.get("geometry", [])
            kinds: dict[str, int] = {}
            for it in geo:
                kinds[it.get("type", "?")] = kinds.get(it.get("type", "?"), 0) + 1
            desc = ", ".join(f"{n} {t}" for t, n in sorted(kinds.items()))
            lines.append(f"  {fid} (Sketch on {sk.get('plane', '?')}): {desc or 'empty'}")
        else:
            params = f.get("parameters", {}) or {}
            keys = ("Length", "Angle", "Diameter", "Depth", "Occurrences",
                    "Value", "Radius", "Size")
            pstr = ", ".join(f"{k}={params[k]}" for k in keys if params.get(k) is not None)
            src = profile_of.get(fid)
            lines.append(f"  {fid} ({ftype}{', ' + pstr if pstr else ''})"
                         + (f" <- profile {src}" if src else ""))
        shown += 1
    return "\n".join(lines)


def parse_graph_arg(value: Any) -> Optional[dict]:
    """Accept the graph tool-argument as dict or JSON string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None
