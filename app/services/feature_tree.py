"""The feature history of a saved part, assembled from three sources.

No single record holds it. What the model authored, what the numbers resolved
to, and what the kernel actually did are produced at different times by
different systems, and the tree is the join:

``blueprint["template"]["features"]``
    the authored feature list, in build order, with every dimension still an
    expression over the part's variables. Persisted in ``designs.feature_graph``.
``Blueprint.resolve()``
    those expressions evaluated to numbers. Deliberately *not* stored — it is a
    pure function of the Blueprint, so storing it would create a second copy
    that could disagree with the contract that was actually hashed and built.
    Recomputed here; it is arithmetic, not geometry, and costs nothing.
``generation_history.execution_trace``
    what FreeCAD reported: the volume each feature added or removed, and which
    features failed to recompute. Only this part can fail to exist — a design
    saved before the build record existed, or saved without its ``request_id``.

The join between the last of these and the first is the fiddly part, and is
explained at ``_match_measured``.

Everything degrades rather than fails: a design with no evidence still returns
its authored tree, with volumes reported as unknown instead of as zero. Zero is
a measurement; ``None`` is the absence of one, and a history tree that shows a
confident 0 mm³ for every feature is worse than one that admits it does not
know.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)

#: Structural entries rather than operations. They appear in the template
#: because the compiler needs them, but a user reading a history wants the
#: features that changed the solid — the same filter the studio applies when it
#: reports build progress.
STRUCTURAL_TYPES = {"Body", "Sketch"}


def _normalise(name: str) -> str:
    """Lowercased alphanumerics, for comparing a FreeCAD name to a feature id."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _match_measured(
    feature_id: str, type_id: str, measured: list[dict], used: set[int]
) -> Optional[dict]:
    """Find the measurement row for one authored feature.

    ``reconstruct.py`` creates each feature as ``doc.addObject(kind, fid)``, so
    the FreeCAD object's ``Name`` is usually the feature id — but *usually* is
    the operative word. FreeCAD sanitises names to a restricted character set
    and appends digits when one is already taken, so an id containing an
    underscore or colliding with an earlier object comes back altered. Matching
    on equality alone silently drops those features' volumes.

    Three passes, narrowing: exact name, then normalised name, then the first
    unclaimed row of the same type in build order. ``used`` stops two features
    claiming one row, which is how a positional fallback would otherwise
    misattribute every volume after a rename.
    """
    for index, row in enumerate(measured):
        if index in used:
            continue
        if str(row.get("name", "")) == feature_id:
            used.add(index)
            return row

    target = _normalise(feature_id)
    for index, row in enumerate(measured):
        if index in used:
            continue
        if _normalise(row.get("name", "")) == target:
            used.add(index)
            return row

    for index, row in enumerate(measured):
        if index in used:
            continue
        if row.get("type_id") == type_id:
            used.add(index)
            return row

    return None


def _resolved_parameters(blueprint: dict) -> tuple[dict[str, dict], bool]:
    """``{feature_id: {param: number}}`` and whether resolution succeeded.

    Uses ``Blueprint.from_dict`` without re-freezing: the stored payload already
    carries its hash, and ``freeze()`` would re-run the static checker against a
    blueprint that was accepted when it was built. A checker that has since
    grown a rule would then refuse to show a part the user already owns, which
    is not the checker's job at read time.
    """
    try:
        from orion.blueprint import Blueprint

        graph = Blueprint.from_dict(blueprint).resolve()
    except Exception as exc:  # noqa: BLE001 — the tree is still worth showing
        logger.warning("feature_tree_resolve_failed", error=repr(exc))
        return {}, False

    return (
        {f["id"]: f.get("parameters") or {} for f in graph.get("features", [])},
        True,
    )


def empty() -> dict[str, Any]:
    """A complete tree with nothing in it.

    Callers that fail to assemble one must return this rather than a partial
    dict: the client's type says every field is present, and a fallback missing
    half of them is a contract violation that only shows up as an undefined
    somewhere in the UI.
    """
    return build(None, None)


def build(blueprint: Optional[dict], evidence: Optional[dict] = None) -> dict[str, Any]:
    """Assemble the feature tree for one saved design."""
    blueprint = blueprint or {}
    evidence = evidence or {}

    template = blueprint.get("template") or {}
    authored = [
        f
        for f in (template.get("features") or [])
        if f.get("type") not in STRUCTURAL_TYPES
    ]

    resolved, resolve_ok = _resolved_parameters(blueprint) if authored else ({}, False)

    measured = list(evidence.get("features") or [])
    errors = {
        str(e.get("id")): e.get("error")
        for e in (evidence.get("recompute_errors") or [])
    }
    unsupported = {
        str(u.get("id") if isinstance(u, dict) else u)
        for u in (evidence.get("unsupported") or [])
    }

    used: set[int] = set()
    features: list[dict] = []
    for entry in authored:
        fid = str(entry.get("id", ""))
        ftype = str(entry.get("type", ""))
        type_id = entry.get("type_id") or _TYPE_IDS.get(ftype, "")
        row = _match_measured(fid, type_id, measured, used) if measured else None

        if fid in errors:
            state = "error"
        elif fid in unsupported:
            state = "unsupported"
        elif row is not None:
            state = "success"
        else:
            # Built or not, nobody told us. Distinct from success on purpose.
            state = "unknown"

        features.append(
            {
                "id": fid,
                "type": ftype,
                "label": entry.get("label") or fid,
                "rationale": entry.get("rationale") or "",
                # Both are useful: the numbers are what was built, the expressions
                # are why. A user changing a variable needs to see which features
                # depend on it.
                "parameters": resolved.get(fid, {}),
                "expressions": entry.get("parameters") or {},
                "volume_delta_mm3": (row or {}).get("addsub_volume"),
                "cumulative_volume_mm3": (row or {}).get("cumulative_volume"),
                "status": state,
                "error": errors.get(fid),
            }
        )

    verification = evidence.get("verification") or {}
    return {
        "part_class": blueprint.get("part_class", ""),
        "blueprint_hash": blueprint.get("blueprint_hash", ""),
        "variables": blueprint.get("variables") or {},
        "features": features,
        # Named so the client can tell "nothing failed" from "nothing was
        # recorded" — the same distinction the verification report makes.
        "evidence_available": bool(measured or errors),
        "parameters_resolved": resolve_ok,
        "verdict": verification.get("verdict") or "",
        "built_where": evidence.get("built_where") or "",
    }


#: Fallback for templates authored before ``type_id`` travelled with a feature.
_TYPE_IDS: dict[str, str] = {}


def _load_type_ids() -> None:
    global _TYPE_IDS
    try:
        from orion.blueprint import TYPE_IDS

        _TYPE_IDS = dict(TYPE_IDS)
    except Exception:  # noqa: BLE001 — only weakens the positional fallback
        _TYPE_IDS = {}


_load_type_ids()
