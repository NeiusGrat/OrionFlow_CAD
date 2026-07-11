"""Synthetic models with programmatically-known ground truth.

A :class:`SyntheticBridge` implements the BridgeClient surface from a declared
:class:`SyntheticModel`, so eval ground truth is computed, not assumed. This
lets the eval harness score grounding/accuracy headless and deterministically,
and lets Modify cases mutate a model and re-measure.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SyntheticModel:
    name: str = "Part"
    type_id: str = "PartDesign::Body"
    tier: str = "B"
    faces: int = 6
    edges: int = 12
    vertices: int = 8
    planar_faces: int = 6
    holes: int = 0                      # cylindrical through-features
    bbox: tuple = (20.0, 10.0, 5.0)
    volume: float = 1000.0
    hole_spacing: Optional[float] = None
    parameters: dict = field(default_factory=dict)

    def topology(self) -> dict:
        surf = {"Plane": self.planar_faces}
        if self.holes:
            surf["Cylinder"] = self.holes
        return {
            "shapes": [{
                "name": self.name, "solids": 1, "faces": self.faces,
                "edges": self.edges, "vertices": self.vertices,
                "surface_types": surf, "cylindrical_faces": self.holes,
                "bounding_box": {"size": list(self.bbox),
                                 "min": [0, 0, 0], "max": list(self.bbox)},
                "volume": self.volume,
                "center_of_mass": [self.bbox[0] / 2, self.bbox[1] / 2, self.bbox[2] / 2],
            }]
        }


class SyntheticBridge:
    """A BridgeClient-compatible stand-in driven by a SyntheticModel."""

    def __init__(self, model: SyntheticModel):
        self.model = copy.deepcopy(model)
        self._error = False

    # ---- read ---------------------------------------------------------- #
    def get_model_tier(self):
        return {"tier": self.model.tier, "rationale": "synthetic"}

    def list_objects(self):
        return {"objects": [{
            "name": self.model.name, "type_id": self.model.type_id,
            "parametric": self.model.tier in ("A", "B"),
            "imported": self.model.tier == "C", "faces": self.model.faces,
            "error": self._error,
        }]}

    def inspect_topology(self, name=None):
        return self.model.topology()

    def get_object_parameters(self, name):
        return {"name": self.model.name, "label": self.model.name,
                "type_id": self.model.type_id, "parameters": dict(self.model.parameters)}

    def measure(self, a, b):
        if self.model.hole_spacing is not None:
            return {"distance": self.model.hole_spacing,
                    "from": [0, 0, 0], "to": [self.model.hole_spacing, 0, 0]}
        return {"distance": float(self.model.bbox[0])}

    def render_views(self, views=None, out_dir=None):
        return {"renders": [], "headless": True}

    def extract_featuregraph(self):
        return {"graph": getattr(self, "_compiled_graph", None) or {
            "features": [], "sketches": [], "dependencies": []}}

    def select(self, refs):
        return {"selected": True}

    # ---- mutate (for Modify eval) -------------------------------------- #
    def begin_transaction(self, label="edit"):
        self._txn_backup = copy.deepcopy(self.model)
        return {"open": True}

    def commit_transaction(self):
        return {"committed": True}

    def abort_transaction(self):
        if hasattr(self, "_txn_backup"):
            self.model = self._txn_backup
        return {"aborted": True}

    def set_parameter(self, name, property, value):  # noqa: A002
        before = self.model.parameters.get(property)
        self.model.parameters[property] = value
        return {"name": name, "property": property, "before": before, "after": value}

    def edit_feature(self, name, properties):
        applied = {}
        for k, v in properties.items():
            applied[k] = {"before": self.model.parameters.get(k), "after": v}
            self.model.parameters[k] = v
        return {"name": name, "applied": applied}

    def import_shape(self, path, label="OrionResult", replace=None, source_code=None):
        return {"created": label} if not replace else {"replaced": replace}

    def compile_featuregraph(self, graph):
        self._compiled_graph = graph
        ids = [f["id"] for f in graph.get("features", []) if f.get("type") != "Body"]
        return {
            "created": ["Body"] + ids,
            "features": ["Body"] + ids,
            "body": "Body",
            "report": {"built": [{"id": i} for i in ids], "unsupported": [],
                       "recompute_errors": [], "doc_recomputed": True,
                       "volume": 1000.0},
            "recompute_ok": True,
        }

    def undo(self):
        return self.abort_transaction()

    def export(self, path, names=None):
        return {"path": path, "objects": names or [self.model.name]}

    def is_alive(self):
        return True
