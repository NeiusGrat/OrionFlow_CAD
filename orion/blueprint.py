"""The Blueprint: a frozen mathematical contract, hashed before any build.

Lifecycle (one-way by construction)::

    author template  →  check (static, no literals)  →  freeze (sha256)
        →  resolve(variables) → concrete FeatureGraph → build → measure
        →  compare against the FROZEN assertions

``blueprint_hash`` covers the canonical JSON of everything the design agent
authored — variables, plan, template, assertions — before FreeCAD ever runs.
Measurement results can therefore never leak back into the contract: a record
whose blueprint hash does not match its stored blueprint is discarded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from . import expr as E
from . import profiles as P

SCHEMA_VERSION = "orion-blueprint-v1"

#: Feature type -> FreeCAD type id, mirroring freecad/reconstruct.py vocabulary.
TYPE_IDS = {
    "Body": "PartDesign::Body",
    "Sketch": "Sketcher::SketchObject",
    "Pad": "PartDesign::Pad",
    "Pocket": "PartDesign::Pocket",
    "Revolution": "PartDesign::Revolution",
    "Groove": "PartDesign::Groove",
    "Hole": "PartDesign::Hole",
    "Loft": "PartDesign::AdditiveLoft",
    "Sweep": "PartDesign::AdditivePipe",
    "Fillet": "PartDesign::Fillet",
    "Chamfer": "PartDesign::Chamfer",
    "Draft": "PartDesign::Draft",
    "Thickness": "PartDesign::Thickness",
    "LinearPattern": "PartDesign::LinearPattern",
    "PolarPattern": "PartDesign::PolarPattern",
    "Mirrored": "PartDesign::Mirrored",
    "Sphere": "PartDesign::AdditiveSphere",
    "Box": "PartDesign::AdditiveBox",
    "Cylinder": "PartDesign::AdditiveCylinder",
    "Cone": "PartDesign::AdditiveCone",
    "Torus": "PartDesign::AdditiveTorus",
}


class BlueprintError(ValueError):
    pass


def canonical_json(obj: Any) -> str:
    """Deterministic serialization — the hashing substrate. repr-stable floats,
    sorted keys, no whitespace variance."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=_reject_unknown)


def _reject_unknown(o):
    raise BlueprintError(f"unhashable object in blueprint: {type(o).__name__}")


@dataclass(frozen=True)
class Blueprint:
    part_class: str
    variables: dict[str, float]
    datums: dict[str, Any]
    design_plan: dict[str, Any]        # intent, mfg, datum strategy, derivations
    assertions: list[dict[str, Any]]   # {id, kind, tier, target, tol_rel, ...}
    template: dict[str, Any]           # feature graph with EXPRESSION params
    version: str = SCHEMA_VERSION
    blueprint_hash: str = ""           # set by freeze(); "" means not frozen

    # ---- freeze ---------------------------------------------------------- #
    def payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "part_class": self.part_class,
            "variables": self.variables,
            "datums": self.datums,
            "design_plan": self.design_plan,
            "assertions": self.assertions,
            "template": self.template,
        }

    def freeze(self) -> "Blueprint":
        """Check, then hash. Returns the frozen copy; the original (hashless)
        instance should be discarded by the caller."""
        from .checker import check_blueprint  # local: avoid import cycle
        problems = check_blueprint(self)
        if problems:
            raise BlueprintError("blueprint failed static check:\n  - "
                                 + "\n  - ".join(problems))
        digest = hashlib.sha256(canonical_json(self.payload()).encode()).hexdigest()
        return Blueprint(**{**self.__dict__, "blueprint_hash": digest})

    def verify_hash(self) -> bool:
        if not self.blueprint_hash:
            return False
        digest = hashlib.sha256(canonical_json(self.payload()).encode()).hexdigest()
        return digest == self.blueprint_hash

    # ---- resolve --------------------------------------------------------- #
    def _num(self, value: Any) -> float:
        return E.evaluate(value, self.variables)

    def resolve(self) -> dict[str, Any]:
        """Expression template -> concrete FeatureGraph (reconstruct.py input).

        Also returns, under ``_analysis``, the exact per-sketch area/centroid
        from the profile builders — the verifier's independent prediction
        inputs. ``_analysis`` is stripped before the graph is handed to the
        compiler and is NOT part of the hash (it is derivable, not authored).
        """
        if not self.blueprint_hash:
            raise BlueprintError("resolve() on an unfrozen blueprint")
        features, sketches, analysis = [], [], {}
        for f in self.template.get("features", []):
            ftype = f["type"]
            if ftype not in TYPE_IDS:
                raise BlueprintError(f"unknown feature type {ftype!r}")
            params: dict[str, Any] = {}
            for k, v in (f.get("parameters") or {}).items():
                if k == "_Edges" and isinstance(v, str) and ":" in v:
                    # Edge selectors carry an embedded expression after the
                    # colon ("radius:hole_r") — resolve it so the selector
                    # stays variable-driven, not a magic number.
                    head, tail = v.split(":", 1)
                    if head in ("radius", "largest"):
                        params[k] = f"{head}:{self._num(tail)}"
                    else:
                        params[k] = v
                elif isinstance(v, str) and not k.startswith("_") \
                        and k not in _ENUM_PARAMS:
                    params[k] = self._num(v)
                else:
                    params[k] = v
            features.append({"id": f["id"], "type": ftype,
                             "type_id": TYPE_IDS[ftype],
                             "label": f.get("label", f["id"]),
                             "parameters": params})
        for sk in self.template.get("sketches", []):
            spec = sk.get("profile")
            if not spec:
                raise BlueprintError(f"sketch {sk['id']!r} has no profile spec")
            args = {k: (self._num(v) if isinstance(v, str) or
                        isinstance(v, (int, float)) else v)
                    for k, v in (spec.get("args") or {}).items()}
            if "holes" in (spec.get("args") or {}):   # nested exprs
                args["holes"] = [tuple(self._num(x) for x in h)
                                 for h in spec["args"]["holes"]]
            if "points" in (spec.get("args") or {}):
                args["points"] = [tuple(self._num(x) for x in p)
                                  for p in spec["args"]["points"]]
            prof = P.build(spec["builder"], **args)
            entry = {"id": sk["id"], "plane": sk.get("plane", "XY"),
                     "constraints": [], "geometry": prof["geometry"]}
            if "z" in sk:
                entry["z"] = self._num(sk["z"])
            sketches.append(entry)
            analysis[sk["id"]] = {"area": prof["area"],
                                  "centroid": prof["centroid"],
                                  "loops": prof["loops"],
                                  "builder": spec["builder"]}
        graph = {
            "schema_version": "ofl_fcstd_v1",
            "source_id": self.blueprint_hash[:10],
            "document": {"name": self.part_class, "label": self.part_class,
                         "object_count": len(features)},
            "features": features,
            "sketches": sketches,
            "dependencies": self.template.get("dependencies", []),
            "parameters": [], "expressions": [], "constraints": [],
            "_analysis": analysis,
        }
        return graph

    def resolve_assertions(self) -> list[dict[str, Any]]:
        """Assertions with target/lo/hi evaluated to concrete numbers."""
        out = []
        for a in self.assertions:
            row = dict(a)
            for key in ("target", "lo", "hi"):
                if isinstance(a.get(key), str):
                    row[f"{key}_value"] = self._num(a[key])
            out.append(row)
        return out

    # ---- io -------------------------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "blueprint_hash": self.blueprint_hash}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Blueprint":
        return Blueprint(
            version=d.get("version", SCHEMA_VERSION),
            part_class=d["part_class"],
            variables=d["variables"],
            datums=d.get("datums", {}),
            design_plan=d.get("design_plan", {}),
            assertions=d.get("assertions", []),
            template=d["template"],
            blueprint_hash=d.get("blueprint_hash", ""),
        )


#: String-valued feature parameters that are enums, not expressions.
_ENUM_PARAMS = {
    "Type", "Type2", "SideType", "Mode", "Transition", "Transformation",
    "DepthType", "DrillPoint", "ThreadType", "HoleCutType", "ThreadSize",
    "ThreadClass", "ThreadFit", "Threaded", "ModelThread", "Join",
}


def perturbed(bp: Blueprint, var: str, delta: float) -> Blueprint:
    """A NEW frozen blueprint with one variable changed — the differential
    test builds this sibling and re-predicts from closed form, so there is no
    finite-difference truncation anywhere."""
    if var not in bp.variables:
        raise BlueprintError(f"no variable {var!r}")
    vs = dict(bp.variables)
    vs[var] = vs[var] + delta
    return Blueprint(part_class=bp.part_class, variables=vs, datums=bp.datums,
                     design_plan=bp.design_plan, assertions=bp.assertions,
                     template=bp.template).freeze()
