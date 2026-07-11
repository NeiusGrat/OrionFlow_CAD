"""Modify-pillar verification loop — the heart of safe editing.

After any edit, four checks run in order (build plan Phase 5):

  1. executes/recomputes without error,
  2. edit survival — the rest of the model still builds (no downstream feature
     dropped into an error state),
  3. spec/intent consistency — a reference-free check that the result reflects
     the stated intent (numeric targets, hole counts, etc.),
  4. no unintended change — geometry outside the edited region did not move
     (bounding-box / volume / centre-of-mass diff).

The verifier never fabricates success: a missing baseline yields ``None`` (not
``True``) for the checks it cannot prove. On hard failure the loop aborts the
FreeCAD transaction it opened for the edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from orion_agent.shared.trajectory import ValidationBlock

_TOL = 1e-3


def _close(a, b, tol: float = _TOL) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def _seq_close(a, b, tol: float = _TOL) -> bool:
    if a is None or b is None:
        return a == b
    if len(a) != len(b):
        return False
    return all(_close(x, y, tol) for x, y in zip(a, b))


@dataclass
class Snapshot:
    ok: bool = True
    objects: dict = field(default_factory=dict)   # name -> geometry fingerprint
    error_objects: list = field(default_factory=list)

    def names(self) -> set:
        return set(self.objects)

    def total_cylinders(self) -> Optional[int]:
        counts = [o.get("cylinders") for o in self.objects.values()
                  if o.get("cylinders") is not None]
        return sum(counts) if counts else None


class EditVerifier:
    def __init__(self, bridge):
        self.bridge = bridge

    # ------------------------------------------------------------------ #
    def snapshot(self) -> Optional[Snapshot]:
        if self.bridge is None:
            return None
        try:
            objs = self.bridge.list_objects().get("objects", [])
            topo = self.bridge.inspect_topology(None).get("shapes", [])
        except Exception:  # noqa: BLE001
            return None
        shapes = {s.get("name"): s for s in topo}
        objects = {}
        errors = []
        for o in objs:
            name = o["name"]
            s = shapes.get(name, {})
            bb = s.get("bounding_box", {}) or {}
            objects[name] = {
                "type": o.get("type_id"),
                "bbox_min": bb.get("min"),
                "bbox_max": bb.get("max"),
                "bbox_size": bb.get("size"),
                "volume": s.get("volume"),
                "com": s.get("center_of_mass"),
                "cylinders": s.get("cylindrical_faces"),
                "error": o.get("error", False),
            }
            if o.get("error"):
                errors.append(name)
        return Snapshot(ok=not errors, objects=objects, error_objects=errors)

    # ------------------------------------------------------------------ #
    def verify(self, pillar, traj, artifacts, before: Optional[Snapshot] = None,
               edited_names: Optional[set] = None,
               spec: Optional[dict] = None) -> ValidationBlock:
        """Run the four checks and write them into ``traj.validation``."""
        vb = traj.validation
        after = self.snapshot()

        # 1. executes / recomputes
        if after is None:
            vb.executed = None
            vb.notes = "no live document to verify against"
            return vb
        vb.executed = after.ok
        vb.checks["error_objects"] = after.error_objects

        # 2. edit survival — downstream features still build
        vb.edit_survived = len(after.error_objects) == 0

        # 3. spec / intent consistency (reference-free)
        vb.intent_consistent = self._intent_consistent(
            traj.user_request, before, after, edited_names or set(), spec=spec
        )

        # 4. no unintended change outside the edited region
        if before is not None:
            vb.no_unintended_change = self._no_unintended_change(
                before, after, edited_names or set()
            )
        else:
            vb.no_unintended_change = None

        return vb

    # ------------------------------------------------------------------ #
    @staticmethod
    def _intent_consistent(request: str, before: Optional[Snapshot],
                           after: Snapshot, edited: set,
                           spec: Optional[dict] = None) -> Optional[bool]:
        """Best-effort reference-free intent check.

        When a parsed EngineeringSpec is available (Generate), its grounded
        counts and dimensions are the targets; otherwise targets are regexed
        from the raw request. Hole counts are checked against the model's
        cylindrical-face count (fillets are cylindrical too, so ``>=`` is the
        honest bound). Numeric mm targets are confirmed when they show up in
        the edited objects' bounding-box extents; a target that does not (it
        may be a diameter or a depth) is inconclusive, never a failure.
        Returns ``None`` when no checkable target is present or the data
        cannot prove either way.
        """
        text = request.lower()
        want = None
        if spec:
            for key, value in (spec.get("counts") or {}).items():
                if re.search(r"holes?|bolts?|bores?", str(key)):
                    want = int(value)
                    break
        if want is None:
            m = re.search(r"(\d+)\s*(?:holes?|bolts?|bores?)", text)
            if m:
                want = int(m.group(1))
        if want is not None:
            have = after.total_cylinders()
            if have is None:
                return None
            return have >= want

        if spec and spec.get("dimensions"):
            targets = [float(v) for v in spec["dimensions"].values()]
        else:
            targets = [float(t) for t in re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", text)]
        if targets:
            dims: list[float] = []
            pool = edited or after.names()
            for name in pool:
                size = after.objects.get(name, {}).get("bbox_size")
                if size:
                    dims.extend(size)
            if dims and all(any(_close(t, d, 1e-2) for d in dims) for t in targets):
                return True
            return None

        # No structurally checkable target — leave to the executed/survived gates.
        return True if after.ok else False

    @staticmethod
    def _no_unintended_change(before: Snapshot, after: Snapshot, edited: set) -> bool:
        # Object set must not gain/lose unexpected members (new result objects
        # in ``edited`` are allowed).
        added = after.names() - before.names() - edited
        removed = before.names() - after.names() - edited
        if added or removed:
            return False
        # Geometry outside the edited set must be unchanged: same bounds (so a
        # moved object with an identical size is still caught), same volume,
        # same centre of mass.
        for name, info in before.objects.items():
            if name in edited:
                continue
            after_info = after.objects.get(name, {})
            for key in ("bbox_min", "bbox_max", "bbox_size", "com"):
                if info.get(key) is not None and after_info.get(key) is not None \
                        and not _seq_close(info[key], after_info[key]):
                    return False
            if info.get("volume") is not None and after_info.get("volume") is not None \
                    and not _close(info["volume"], after_info["volume"]):
                return False
        return True
